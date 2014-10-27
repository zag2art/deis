#!/usr/bin/env python
"""
The Deis command-line client issues API calls to a Deis controller.

Usage: deis <command> [<args>...]

Auth commands::

  register      register a new user with a controller
  login         login to a controller
  logout        logout from the current controller

Subcommands, use ``deis help [subcommand]`` to learn more::

  apps          manage applications used to provide services
  ps            manage processes inside an app container
  config        manage environment variables that define app config
  domains       manage and assign domain names to your applications
  builds        manage builds created using `git push`
  limits        manage resource limits for your application
  tags          manage tags for application containers
  releases      manage releases of an application

  keys          manage ssh keys used for `git push` deployments
  perms         manage permissions for applications

Developer shortcut commands::

  create        create a new application
  scale         scale processes by type (web=2, worker=1)
  info          view information about the current app
  open          open a URL to the app in a browser
  logs          view aggregated log info for the app
  run           run a command in an ephemeral app container
  destroy       destroy an application

Use ``git push deis master`` to deploy to an application.

"""

from __future__ import print_function
from collections import namedtuple
from collections import OrderedDict
from datetime import datetime
from getpass import getpass
from itertools import cycle
from threading import Event
from threading import Thread
import base64
import glob
import json
import locale
import logging
import os.path
import re
import subprocess
import sys
import time
import urlparse
import webbrowser

from dateutil import parser
from dateutil import relativedelta
from dateutil import tz
from docopt import docopt
from docopt import DocoptExit
import requests
from termcolor import colored

__version__ = '0.14.1+git'


locale.setlocale(locale.LC_ALL, '')


class Session(requests.Session):
    """
    Session for making API requests and interacting with the filesystem
    """

    def __init__(self):
        super(Session, self).__init__()
        self.trust_env = False
        config_dir = os.path.expanduser('~/.deis')
        self.proxies = {
            "http": os.getenv("http_proxy"),
            "https": os.getenv("https_proxy")
        }
        # Create the $HOME/.deis dir if it doesn't exist
        if not os.path.isdir(config_dir):
            os.mkdir(config_dir, 0700)

    @property
    def app(self):
        """Retrieve the application's name."""
        try:
            return self._get_name_from_git_remote(self.git_root())
        except EnvironmentError:
            return os.path.basename(os.getcwd())

    def is_git_app(self):
        """Determines if this app is a git repository. This is important in special cases
        where we need to know whether or not we should use Deis' automatic app name
        generator, for example.
        """
        try:
            self.git_root()
            return True
        except EnvironmentError:
            return False

    def git_root(self):
        """
        Returns the absolute path from the git repository root.

        If no git repository exists, raises an EnvironmentError.
        """
        try:
            git_root = subprocess.check_output(
                ['git', 'rev-parse', '--show-toplevel'],
                stderr=subprocess.PIPE).strip('\n')
        except subprocess.CalledProcessError:
            raise EnvironmentError('Current directory is not a git repository')
        return git_root

    def _get_name_from_git_remote(self, git_root):
        """
        Retrieves the application name from a git repository root.

        The application is determined by parsing `git remote -v` output.
        If no application is found, raises an EnvironmentError.
        """
        remotes = subprocess.check_output(['git', 'remote', '-v'],
                                          cwd=git_root)
        m = re.search(r'^deis\W+(?P<url>\S+)\W+\(', remotes, re.MULTILINE)
        if not m:
            raise EnvironmentError(
                'Could not find deis remote in `git remote -v`')
        url = m.groupdict()['url']
        m = re.match('\S+/(?P<app>[a-z0-9-]+)(.git)?$', url)
        if not m:
            raise EnvironmentError("Could not parse: {url}".format(**locals()))
        return m.groupdict()['app']

    def request(self, *args, **kwargs):
        """
        Issue an HTTP request
        """
        url = args[1]
        if 'headers' in kwargs:
            kwargs['headers']['Referer'] = url
        else:
            kwargs['headers'] = {'Referer': url}
        response = super(Session, self).request(*args, **kwargs)
        return response


class Settings(dict):
    """
    Settings backed by a file in the user's home directory

    On init, settings are loaded from ~/.deis/client.json
    """

    def __init__(self):
        path = os.path.expanduser('~/.deis')
        # Create the $HOME/.deis dir if it doesn't exist
        if not os.path.isdir(path):
            os.mkdir(path, 0700)
        self._path = os.path.join(path, 'client.json')
        if not os.path.exists(self._path):
            settings = {}
            # try once to convert the old settings file if it exists
            # FIXME: this code can be removed in November 2014 or thereabouts, that's long enough.
            old_path = os.path.join(path, 'client.yaml')
            if os.path.exists(old_path):
                try:
                    with open(old_path, 'r') as f:
                        txt = f.read().replace('{', '{"', 1).replace(':', '":', 1).replace("'", '"')
                        settings = json.loads(txt)
                        os.remove(old_path)
                except:
                    pass  # ignore errors, at least we tried to convert it
            with open(self._path, 'w') as f:
                json.dump(settings, f)
        # load initial settings
        self.load()

    def load(self):
        """
        Deserialize and load settings from the filesystem
        """
        with open(self._path) as f:
            data = f.read()
        settings = json.loads(data)
        self.update(settings)
        return settings

    def save(self):
        """
        Serialize and save settings to the filesystem
        """
        data = json.dumps(dict(self))
        with open(self._path, 'w') as f:
            f.write(data)
        return data


_counter = 0


def _newname(template="Thread-{}"):
    """Generate a new thread name."""
    global _counter
    _counter += 1
    return template.format(_counter)


FRAMES = {
    'arrow': ['^', '>', 'v', '<'],
    'dots': ['...', 'o..', '.o.', '..o'],
    'ligatures': ['bq', 'dp', 'qb', 'pd'],
    'lines': [' ', '-', '=', '#', '=', '-'],
    'slash': ['-', '\\', '|', '/'],
}


class TextProgress(Thread):
    """Show progress for a long-running operation on the command-line."""

    def __init__(self, group=None, target=None, name=None, args=(), kwargs={}):
        name = name or _newname("TextProgress-Thread-{}")
        style = kwargs.get('style', 'dots')
        super(TextProgress, self).__init__(
            group, target, name, args, kwargs)
        self.daemon = True
        self.cancelled = Event()
        self.frames = cycle(FRAMES[style])

    def run(self):
        """Write ASCII progress animation frames to stdout."""
        if not os.environ.get('DEIS_HIDE_PROGRESS'):
            time.sleep(0.5)
            self._write_frame(self.frames.next(), erase=False)
            while not self.cancelled.is_set():
                time.sleep(0.4)
                self._write_frame(self.frames.next())
            # clear the animation
            sys.stdout.write('\b' * (len(self.frames.next()) + 2))
            sys.stdout.flush()

    def cancel(self):
        """Set the animation thread as cancelled."""
        self.cancelled.set()

    def _write_frame(self, frame, erase=True):
        if erase:
            backspaces = '\b' * (len(frame) + 2)
        else:
            backspaces = ''
        sys.stdout.write("{} {} ".format(backspaces, frame))
        # flush stdout or we won't see the frame
        sys.stdout.flush()


def dictify(args):
    """Converts a list of key=val strings into a python dict.

    >>> dictify(['MONGODB_URL=http://mongolabs.com/test', 'scale=5'])
    {'MONGODB_URL': 'http://mongolabs.com/test', 'scale': 5}
    """
    data = {}
    for arg in args:
        try:
            var, val = arg.split('=', 1)
        except ValueError:
            raise DocoptExit()
        # Try to coerce the value to an int since that's a common use case
        try:
            data[var] = int(val)
        except ValueError:
            data[var] = val
    return data


def encode(obj):
    """Return UTF-8 encoding for string objects."""
    if isinstance(obj, basestring):
        return obj.encode('utf-8')
    else:
        return obj


def readable_datetime(datetime_str):
    """
    Return a human-readable datetime string from an ECMA-262 (JavaScript)
    datetime string.
    """
    timezone = tz.tzlocal()
    dt = parser.parse(datetime_str).astimezone(timezone)
    now = datetime.now(timezone)
    delta = relativedelta.relativedelta(now, dt)
    # if it happened today, say "2 hours and 1 minute ago"
    if delta.days <= 1 and dt.day == now.day:
        if delta.hours == 0:
            hour_str = ''
        elif delta.hours == 1:
            hour_str = '1 hour '
        else:
            hour_str = "{} hours ".format(delta.hours)
        if delta.minutes == 0:
            min_str = ''
        elif delta.minutes == 1:
            min_str = '1 minute '
        else:
            min_str = "{} minutes ".format(delta.minutes)
        if not any((hour_str, min_str)):
            return 'Just now'
        else:
            return "{}{}ago".format(hour_str, min_str)
    # if it happened yesterday, say "yesterday at 3:23 pm"
    yesterday = now + relativedelta.relativedelta(days=-1)
    if delta.days <= 2 and dt.day == yesterday.day:
        return dt.strftime("Yesterday at %X")
    # otherwise return locale-specific date/time format
    else:
        return dt.strftime('%c %Z')


def trim(docstring):
    """
    Function to trim whitespace from docstring

    c/o PEP 257 Docstring Conventions
    <http://www.python.org/dev/peps/pep-0257/>
    """
    if not docstring:
        return ''
    # Convert tabs to spaces (following the normal Python rules)
    # and split into a list of lines:
    lines = docstring.expandtabs().splitlines()
    # Determine minimum indentation (first line doesn't count):
    indent = sys.maxint
    for line in lines[1:]:
        stripped = line.lstrip()
        if stripped:
            indent = min(indent, len(line) - len(stripped))
    # Remove indentation (first line is special):
    trimmed = [lines[0].strip()]
    if indent < sys.maxint:
        for line in lines[1:]:
            trimmed.append(line[indent:].rstrip())
    # Strip off trailing and leading blank lines:
    while trimmed and not trimmed[-1]:
        trimmed.pop()
    while trimmed and not trimmed[0]:
        trimmed.pop(0)
    # Return a single string:
    return '\n'.join(trimmed)


class ResponseError(Exception):
    pass


class DeisClient(object):
    """
    A client which interacts with a Deis controller.
    """

    def __init__(self):
        self._session = Session()
        self._settings = Settings()
        self._logger = logging.getLogger(__name__)

    def _dispatch(self, method, path, body=None, **kwargs):
        """
        Dispatch an API request to the active Deis controller
        """
        func = getattr(self._session, method.lower())
        controller = self._settings.get('controller')
        token = self._settings.get('token')
        if not token:
            raise EnvironmentError(
                'Could not find token. Use `deis login` or `deis register` to get started.')
        url = urlparse.urljoin(controller, path, **kwargs)
        headers = {
            'content-type': 'application/json',
            'X-Deis-Version': __version__.rsplit('.', 1)[0],
            'Authorization': 'token {}'.format(token)
        }
        response = func(url, data=body, headers=headers)
        return response

    def apps(self, args):
        """
        Valid commands for apps:

        apps:create        create a new application
        apps:list          list accessible applications
        apps:info          view info about an application
        apps:open          open the application in a browser
        apps:logs          view aggregated application logs
        apps:run           run a command in an ephemeral app container
        apps:destroy       destroy an application

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'apps:list'
        args = docopt(self.apps_list.__doc__)
        return self.apps_list(args)

    def apps_create(self, args):
        """
        Creates a new application.

        - if no <id> is provided, one will be generated automatically.

        Usage: deis apps:create [<id>] [options]

        Arguments:
          <id>
            a uniquely identifiable name for the application. No other app can already
            exist with this name.

        Options:
          --no-remote
            do not create a `deis` git remote.
        """
        body = {}
        app_name = None
        if not self._session.is_git_app():
            app_name = self._session.app
        # prevent app name from being reset to None
        if args.get('<id>'):
            app_name = args.get('<id>')
        if app_name:
            body.update({'id': app_name})
        sys.stdout.write('Creating application... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', '/v1/apps',
                                      json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            data = response.json()
            app_id = data['id']
            self._logger.info("done, created {}".format(app_id))
            # set a git remote if necessary
            try:
                self._session.git_root()
            except EnvironmentError:
                return
            hostname = urlparse.urlparse(self._settings['controller']).netloc.split(':')[0]
            git_remote = "ssh://git@{hostname}:2222/{app_id}.git".format(**locals())
            if args.get('--no-remote'):
                self._logger.info('remote available at {}'.format(git_remote))
            else:
                try:
                    subprocess.check_call(
                        ['git', 'remote', 'add', '-f', 'deis', git_remote],
                        stdout=subprocess.PIPE)
                    self._logger.info('Git remote deis added')
                except subprocess.CalledProcessError:
                    self._logger.error('Could not create Deis remote')
                    sys.exit(1)
        else:
            raise ResponseError(response)

    def apps_destroy(self, args):
        """
        Destroys an application.

        Usage: deis apps:destroy [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.

          --confirm=<app>
            skips the prompt for the application name. <app> is the uniquely identifiable
            name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        confirm = args.get('--confirm')
        if confirm == app:
            pass
        else:
            self._logger.warning("""
 !    WARNING: Potentially Destructive Action
 !    This command will destroy the application: {app}
 !    To proceed, type "{app}" or re-run this command with --confirm={app}
""".format(**locals()))
            confirm = raw_input('> ').strip('\n')
            if confirm != app:
                self._logger.info('Destroy aborted')
                return
        self._logger.info("Destroying {}... ".format(app))
        try:
            progress = TextProgress()
            progress.start()
            before = time.time()
            response = self._dispatch('delete', "/v1/apps/{}".format(app))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code in (requests.codes.no_content,
                                    requests.codes.not_found):
            self._logger.info('done in {}s'.format(int(time.time() - before)))
            try:
                # If the requested app is a heroku app, delete the git remote
                if self._session.is_git_app():
                    subprocess.check_call(
                        ['git', 'remote', 'rm', 'deis'],
                        stdout=subprocess.PIPE, stderr=subprocess.PIPE)
                    self._logger.info('Git remote deis removed')
            except (EnvironmentError, subprocess.CalledProcessError):
                pass  # ignore error
        else:
            raise ResponseError(response)

    def apps_list(self, args):
        """
        Lists applications visible to the current user.

        Usage: deis apps:list
        """
        response = self._dispatch('get', '/v1/apps')
        if response.status_code == requests.codes.ok:
            data = response.json()
            self._logger.info('=== Apps')
            for item in data['results']:
                self._logger.info('{id}'.format(**item))
        else:
            raise ResponseError(response)

    def apps_info(self, args):
        """
        Prints info about the current application.

        Usage: deis apps:info [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch('get', "/v1/apps/{}".format(app))
        if response.status_code == requests.codes.ok:
            self._logger.info("=== {} Application".format(app))
            self._logger.info(json.dumps(response.json(), indent=2) + '\n')
            self.ps_list(args)
            self.domains_list(args)
            self._logger.info('')
        else:
            raise ResponseError(response)

    def apps_open(self, args):
        """
        Opens a URL to the application in the default browser.

        Usage: deis apps:open [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        # TODO: replace with a single API call to apps endpoint
        response = self._dispatch('get', "/v1/apps/{}".format(app))
        if response.status_code == requests.codes.ok:
            url = response.json()['url']
            # use the OS's default handler to open this URL
            webbrowser.open('http://{}/'.format(url))
            return url
        else:
            raise ResponseError(response)

    def apps_logs(self, args):
        """
        Retrieves the most recent log events.

        Usage: deis apps:logs [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch('get',
                                  "/v1/apps/{}/logs".format(app))
        if response.status_code == requests.codes.ok:
            # strip the last newline character
            for line in response.json().split('\n')[:-1]:
                # get the tag from the log
                log_tag = line.split(': ')[0].split(' ')[1]
                # colorize the log based on the tag
                color = sum([ord(ch) for ch in log_tag]) % 6
                def f(x):
                    return {
                        0: 'green',
                        1: 'cyan',
                        2: 'red',
                        3: 'yellow',
                        4: 'blue',
                        5: 'magenta',
                    }.get(x, 'magenta')
                self._logger.info(colored(line, f(color)))
        else:
            raise ResponseError(response)

    def apps_run(self, args):
        """
        Runs a command inside an ephemeral app container. Default environment is
        /bin/bash.

        Usage: deis apps:run [options] [--] <command>...

        Arguments:
          <command>
            the shell command to run inside the container.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        command = ' '.join(args.get('<command>'))
        self._logger.info('Running `{}`...'.format(command))

        app = args.get('--app')
        if not app:
            app = self._session.app
        body = {'command': command}
        response = self._dispatch('post',
                                  "/v1/apps/{}/run".format(app),
                                  json.dumps(body))
        if response.status_code == requests.codes.ok:
            rc, output = json.loads(response.content)
            sys.stdout.write(output)
            sys.stdout.flush()
            sys.exit(rc)
        else:
            raise ResponseError(response)

    def auth(self, args):
        """
        Valid commands for auth:

        auth:register          register a new user
        auth:login             authenticate against a controller
        auth:logout            clear the current user session
        auth:passwd            change the password for the current user
        auth:whoami            display the current user
        auth:cancel            remove the current user account

        Use `deis help [command]` to learn more.
        """
        return

    def auth_register(self, args):
        """
        Registers a new user with a Deis controller.

        Usage: deis auth:register <controller> [options]

        Arguments:
          <controller>
            fully-qualified controller URI, e.g. `http://deis.local.deisapp.com/`

        Options:
          --username=<username>
            provide a username for the new account.
          --password=<password>
            provide a password for the new account.
          --email=<email>
            provide an email address.
        """
        controller = args['<controller>']
        if not urlparse.urlparse(controller).scheme:
            controller = "http://{}".format(controller)
        username = args.get('--username')
        if not username:
            username = raw_input('username: ')
        password = args.get('--password')
        if not password:
            password = getpass('password: ')
            confirm = getpass('password (confirm): ')
            if password != confirm:
                self._logger.error('Password mismatch, aborting registration.')
                sys.exit(1)
        email = args.get('--email')
        if not email:
            email = raw_input('email: ')
        url = urlparse.urljoin(controller, '/v1/auth/register')
        payload = {'username': username, 'password': password, 'email': email}
        response = self._session.post(url, data=payload, allow_redirects=False)
        if response.status_code == requests.codes.created:
            self._settings['controller'] = controller
            self._settings.save()
            self._logger.info("Registered {}".format(username))
            login_args = {'--username': username, '--password': password,
                          '<controller>': controller}
            if self.auth_login(login_args) is False:
                self._logger.info('Login failed')
        else:
            self._logger.info('Registration failed: ' + response.content)
            sys.exit(1)
        return True

    def auth_cancel(self, args):
        """
        Cancels and removes the current account.

        Usage: deis auth:cancel
        """
        controller = self._settings.get('controller')
        if not controller:
            self._logger.error('Not logged in to a Deis controller')
            sys.exit(1)
        self._logger.info('Please log in again in order to cancel this account')
        username = self.auth_login({'<controller>': controller})
        if username:
            confirm = raw_input("Cancel account \"{}\" at {}? (y/n) ".format(username, controller))
            if confirm == 'y':
                self._dispatch('delete', '/v1/auth/cancel')
                self._settings['controller'] = None
                self._settings['token'] = None
                self._settings.save()
                self._logger.info('Account cancelled')
            else:
                self._logger.info('Account not changed')

    def auth_login(self, args):
        """
        Logs in by authenticating against a controller.

        Usage: deis auth:login <controller> [options]

        Arguments:
          <controller>
            a fully-qualified controller URI, e.g. `http://deis.local.deisapp.com/`.

        Options:
          --username=<username>
            provide a username for the account.
          --password=<password>
            provide a password for the account.
        """
        controller = args['<controller>']
        if not urlparse.urlparse(controller).scheme:
            controller = "http://{}".format(controller)
        username = args.get('--username')
        headers = {}
        if not username:
            username = raw_input('username: ')
        password = args.get('--password')
        if not password:
            password = getpass('password: ')
        url = urlparse.urljoin(controller, '/v1/auth/login/')
        payload = {'username': username, 'password': password}
        # post credentials to the login URL
        response = self._session.post(url, data=payload, allow_redirects=False)
        if response.status_code == requests.codes.ok:
            # retrieve and save the API token for future requests
            self._settings['controller'] = controller
            self._settings['username'] = username
            self._settings['token'] = response.json()['token']
            self._settings.save()
            self._logger.info("Logged in as {}".format(username))
            return username
        else:
            raise ResponseError(response)

    def auth_logout(self, args):
        """
        Logs out from a controller and clears the user session.

        Usage: deis auth:logout
        """
        self._settings['controller'] = None
        self._settings['username'] = None
        self._settings['token'] = None
        self._settings.save()
        self._logger.info('Logged out')

    def auth_passwd(self, args):
        """
        Changes the password for the current user.

        Usage: deis auth:passwd [options]

        Options:
          --password=<password>
            provide the current password for the account.
          --new-password=<new-password>
            provide a new password for the account.
        """
        if not self._settings.get('token'):
            raise EnvironmentError(
                'Could not find token. Use `deis login` or `deis register` to get started.')
        password = args.get('--password')
        if not password:
            password = getpass('current password: ')
        new_password = args.get('--new-password')
        if not new_password:
            new_password = getpass('new password: ')
            confirm = getpass('new password (confirm): ')
            if new_password != confirm:
                self._logger.error('Password mismatch, not changing.')
                sys.exit(1)
        payload = {'password': password, 'new_password': new_password}
        response = self._dispatch('post', "/v1/auth/passwd", json.dumps(payload))
        if response.status_code == requests.codes.ok:
            self._logger.info('Password change succeeded.')
        else:
            self._logger.info("Password change failed: {}".format(response.text))
            sys.exit(1)
        return True

    def auth_whoami(self, args):
        """
        Displays the currently logged in user.

        Usage: deis auth:whoami
        """
        user = self._settings.get('username')
        if user:
            self._logger.info(user)
        else:
            self._logger.info(
                'Not logged in. Use `deis login` or `deis register` to get started.')

    def builds(self, args):
        """
        Valid commands for builds:

        builds:list        list build history for an application
        builds:create      imports an image and deploys as a new release

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'builds:list'
        args = docopt(self.builds_list.__doc__)
        return self.builds_list(args)

    def builds_create(self, args):
        """
        Creates a new build of an application. Imports an <image> and deploys it to Deis
        as a new release.

        Usage: deis builds:create <image> [options]

        Arguments:
          <image>
            A fully-qualified docker image, either from Docker Hub (e.g. deis/example-go)
            or from an in-house registry (e.g. myregistry.example.com:5000/example-go).

        Options:
          -a --app=<app>
            The uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        body = {'image': args['<image>']}
        sys.stdout.write('Creating build... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', "/v1/apps/{}/builds".format(app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            version = response.headers['x-deis-release']
            self._logger.info("done, v{}".format(version))
        else:
            raise ResponseError(response)

    def builds_list(self, args):
        """
        Lists build history for an application.

        Usage: deis builds:list [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch('get', "/v1/apps/{}/builds".format(app))
        if response.status_code == requests.codes.ok:
            self._logger.info("=== {} Builds".format(app))
            data = response.json()
            for item in data['results']:
                self._logger.info("{0[uuid]:<23} {0[created]}".format(item))
        else:
            raise ResponseError(response)

    def config(self, args):
        """
        Valid commands for config:

        config:list        list environment variables for an app
        config:set         set environment variables for an app
        config:unset       unset environment variables for an app
        config:pull        extract environment variables to .env

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'config:list'
        args = docopt(self.config_list.__doc__)
        return self.config_list(args)

    def config_list(self, args):
        """
        Lists environment variables for an application.

        Usage: deis config:list [options]

        Options:
          --oneline
            print output on one line.

          -a --app=<app>
            the uniquely identifiable name of the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app

        oneline = args.get('--oneline')
        response = self._dispatch('get', "/v1/apps/{}/config".format(app))
        if response.status_code == requests.codes.ok:
            config = response.json()
            values = config['values']
            self._logger.info("=== {} Config".format(app))
            items = values.items()
            if len(items) == 0:
                self._logger.info('No configuration')
                return
            keys = sorted(values)

            if not oneline:
                width = max(map(len, keys)) + 5
                for k in keys:
                    k, v = encode(k), encode(values[k])
                    self._logger.info(("{k:<" + str(width) + "} {v}").format(**locals()))
            else:
                output = []
                for k in keys:
                    k, v = encode(k), encode(values[k])
                    output.append("{k}={v}".format(**locals()))
                self._logger.info(' '.join(output))
        else:
            raise ResponseError(response)

    def config_set(self, args):
        """
        Sets environment variables for an application.

        Usage: deis config:set <var>=<value> [<var>=<value>...] [options]

        Arguments:
          <var>
            the uniquely identifiable name for the environment variable.
          <value>
            the value of said environment variable.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        body = {'values': json.dumps(dictify(args['<var>=<value>']))}
        sys.stdout.write('Creating config... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', "/v1/apps/{}/config".format(app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            version = response.headers['x-deis-release']
            self._logger.info("done, v{}\n".format(version))
            config = response.json()
            values = config['values']
            self._logger.info("=== {}".format(app))
            items = values.items()
            if len(items) == 0:
                self._logger.info('No configuration')
                return
            for k, v in values.items():
                self._logger.info("{}: {}".format(encode(k), encode(v)))
        else:
            raise ResponseError(response)

    def config_unset(self, args):
        """
        Unsets an environment variable for an application.

        Usage: deis config:unset <key>... [options]

        Arguments:
          <key>
            the variable to remove from the application's environment.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        values = {}
        for k in args.get('<key>'):
            values[k] = None
        body = {'values': json.dumps(values)}
        sys.stdout.write('Creating config... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch(
                'post', "/v1/apps/{}/config".format(app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            version = response.headers['x-deis-release']
            self._logger.info("done, v{}\n".format(version))
            config = response.json()
            values = config['values']
            self._logger.info("=== {}".format(app))
            items = values.items()
            if len(items) == 0:
                self._logger.info('No configuration')
                return
            for k, v in values.items():
                self._logger.info("{k}: {v}".format(**locals()))
        else:
            raise ResponseError(response)

    def config_pull(self, args):
        """
        Extract all environment variables from an application for local use.

        Your environment will be stored locally in a file named .env. This file can be
        read by foreman to load the local environment for your app.

        Usage: deis config:pull [options]

        Options:
          -a --app=<app>
            The application that you wish to pull from
          -i --interactive
            Prompts for each value to be overwritten
          -o --overwrite
            Allows you to have the pull overwrite keys in .env
        """
        app = args.get('--app')
        overwrite = args.get('--overwrite')
        interactive = args.get('--interactive')
        env_dict = {}
        if not app:
            app = self._session.app
            try:
                # load env_dict from existing .env, if it exists
                with open('.env') as f:
                    for line in f.readlines():
                        k, v = line.split('=', 1)[0], line.split('=', 1)[1].strip('\n')
                        env_dict[k] = v
            except IOError:
                pass
        response = self._dispatch('get', "/v1/apps/{}/config".format(app))
        if response.status_code == requests.codes.ok:
            config = response.json()['values']
            for k, v in config.items():
                if interactive and raw_input("overwrite {} with {}? (y/N) ".format(k, v)) == 'y':
                    env_dict[k] = v
                if k in env_dict and not overwrite:
                    continue
                env_dict[k] = v
            # write env_dict to .env
            try:
                with open('.env', 'w') as f:
                    for i in env_dict.keys():
                        f.write("{}={}\n".format(i, env_dict[i]))
            except IOError:
                self._logger.error('could not write to local env')
                sys.exit(1)
        else:
            raise ResponseError(response)

    def domains(self, args):
        """
        Valid commands for domains:

        domains:add           bind a domain to an application
        domains:list          list domains bound to an application
        domains:remove        unbind a domain from an application

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'domains:list'
        args = docopt(self.domains_list.__doc__)
        return self.domains_list(args)

    def domains_add(self, args):
        """
        Binds a domain to an application.

        Usage: deis domains:add <domain> [options]

        Arguments:
          <domain>
            the domain name to be bound to the application, such as `domain.deisapp.com`.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        domain = args.get('<domain>')
        body = {'domain': domain}
        sys.stdout.write("Adding {domain} to {app}... ".format(**locals()))
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch(
                'post', "/v1/apps/{app}/domains".format(app=app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            self._logger.info("done")
        else:
            raise ResponseError(response)

    def domains_remove(self, args):
        """
        Unbinds a domain for an application.

        Usage: deis domains:remove <domain> [options]

        Arguments:
          <domain>
            the domain name to be removed from the application.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        domain = args.get('<domain>')
        sys.stdout.write("Removing {domain} from {app}... ".format(**locals()))
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch(
                'delete', "/v1/apps/{app}/domains/{domain}".format(**locals()))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.no_content:
            self._logger.info("done")
        else:
            raise ResponseError(response)

    def domains_list(self, args):
        """
        Lists domains bound to an application.

        Usage: deis domains:list [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch(
            'get', "/v1/apps/{app}/domains".format(app=app))
        if response.status_code == requests.codes.ok:
            domains = response.json()['results']
            self._logger.info("=== {} Domains".format(app))
            if len(domains) == 0:
                self._logger.info('No domains')
                return
            for domain in domains:
                self._logger.info(domain['domain'])
        else:
            raise ResponseError(response)

    def limits(self, args):
        """
        Valid commands for limits:

        limits:list        list resource limits for an app
        limits:set         set resource limits for an app
        limits:unset       unset resource limits for an app

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'limits:list'
        args = docopt(self.limits_list.__doc__)
        return self.limits_list(args)

    def limits_list(self, args):
        """
        Lists resource limits for an application.

        Usage: deis limits:list [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name of the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch('get', "/v1/apps/{}/config".format(app))
        if response.status_code == requests.codes.ok:
            self._print_limits(app, response.json())
        else:
            raise ResponseError(response)

    def limits_set(self, args):
        """
        Sets resource limits for an application.

        A resource limit is a finite resource within a container which we can apply
        restrictions to either through the scheduler or through the Docker API. This limit
        is applied to each individual container, so setting a memory limit of 1G for an
        application means that each container gets 1G of memory.

        Usage: deis limits:set [options] <type>=<limit>...

        Arguments:
          <type>
            the process type as defined in your Procfile, such as 'web' or 'worker'.
            Note that Dockerfile apps have a default 'cmd' process type.
          <limit>
            The limit to apply to the process type. By default, this is set to --memory.
            You can only set one type of limit per call.

            With --memory, units are represented in Bytes (B), Kilobytes (K), Megabytes
            (M), or Gigabytes (G). For example, `deis limit:set cmd=1G` will restrict all
            "cmd" processes to a maximum of 1 Gigabyte of memory each.

            With --cpu, units are represented in the number of cpu shares. For example,
            `deis limit:set --cpu cmd=1024` will restrict all "cmd" processes to a
            maximum of 1024 cpu shares.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
          -c --cpu
            limits cpu shares.
          -m --memory
            limits memory. [default: true]
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        body = {}
        # see if cpu shares are being specified, otherwise default to memory
        target = 'cpu' if args.get('--cpu') else 'memory'
        body[target] = json.dumps(dictify(args['<type>=<limit>']))
        sys.stdout.write('Applying limits... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', "/v1/apps/{}/config".format(app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            version = response.headers['x-deis-release']
            self._logger.info("done, v{}\n".format(version))

            self._print_limits(app, response.json())
        else:
            raise ResponseError(response)

    def limits_unset(self, args):
        """
        Unsets resource limits for an application.

        Usage: deis limits:unset [options] [--memory | --cpu] <type>...

        Arguments:
          <type>
            the process type as defined in your Procfile, such as 'web' or 'worker'.
            Note that Dockerfile apps have a default 'cmd' process type.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
          -c --cpu
            limits cpu shares.
          -m --memory
            limits memory. [default: true]
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        values = {}
        for k in args.get('<type>'):
            values[k] = None
        body = {}
        # see if cpu shares are being specified, otherwise default to memory
        target = 'cpu' if args.get('--cpu') else 'memory'
        body[target] = json.dumps(values)
        sys.stdout.write('Applying limits... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', "/v1/apps/{}/config".format(app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            version = response.headers['x-deis-release']
            self._logger.info("done, v{}\n".format(version))
            self._print_limits(app, response.json())
        else:
            raise ResponseError(response)

    def _print_limits(self, app, config):
        self._logger.info("=== {} Limits".format(app))

        def write(d):
            items = d.items()
            if len(items) == 0:
                self._logger.info('Unlimited')
                return
            keys = sorted(d)
            width = max(map(len, keys)) + 5
            for k in keys:
                v = d[k]
                self._logger.info(("{k:<" + str(width) + "} {v}").format(**locals()))

        self._logger.info("\n--- Memory")
        write(config.get('memory', '{}'))
        self._logger.info("\n--- CPU")
        write(config.get('cpu', '{}'))

    def ps(self, args):
        """
        Valid commands for processes:

        ps:list        list application processes
        ps:scale       scale processes (e.g. web=4 worker=2)

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'ps:list'
        args = docopt(self.ps_list.__doc__)
        return self.ps_list(args)

    def ps_list(self, args, app=None):
        """
        Lists processes servicing an application.

        Usage: deis ps:list [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        if not app:
            app = args.get('--app')
            if not app:
                app = self._session.app
        response = self._dispatch('get',
                                  "/v1/apps/{}/containers".format(app))
        if response.status_code != requests.codes.ok:
            raise ResponseError(response)
        processes = response.json()
        self._logger.info("=== {} Processes\n".format(app))
        c_map = {}
        for item in processes['results']:
            c_map.setdefault(item['type'], []).append(item)
        for c_type in c_map.keys():
            self._logger.info("--- {c_type}: ".format(**locals()))
            for c in c_map[c_type]:
                self._logger.info("{type}.{num} {state} ({release})".format(**c))
            self._logger.info('')

    def ps_scale(self, args):
        """
        Scales an application's processes by type.

        Usage: deis ps:scale <type>=<num>... [options]

        Arguments:
          <type>
            the process name as defined in your Procfile, such as 'web' or 'worker'.
            Note that Dockerfile apps have a default 'cmd' process type.
          <num>
            the number of processes.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        body = {}
        for type_num in args.get('<type>=<num>'):
            typ, count = type_num.split('=')
            body.update({typ: int(count)})
        sys.stdout.write('Scaling processes... but first, coffee!\n')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            before = time.time()
            response = self._dispatch('post',
                                      "/v1/apps/{}/scale".format(app),
                                      json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.no_content:
            self._logger.info('done in {}s'.format(int(time.time() - before)))
            self.ps_list({}, app)
        else:
            raise ResponseError(response)

    def tags(self, args):
        """
        Valid commands for tags:

        tags:list        list tags for an app
        tags:set         set tags for an app
        tags:unset       unset tags for an app

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'tags:list'
        args = docopt(self.tags_list.__doc__)
        return self.tags_list(args)

    def tags_list(self, args):
        """
        Lists tags for an application.

        Usage: deis tags:list [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name of the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch('get', "/v1/apps/{}/config".format(app))
        if response.status_code == requests.codes.ok:
            self._print_tags(app, response.json())
        else:
            raise ResponseError(response)

    def tags_set(self, args):
        """
        Sets tags for an application.

        A tag is a key/value pair used to tag an application's containers.
        This is often used to restrict workloads to specific hosts.

        Usage: deis tags:set [options] <key>=<value>...

        Arguments:
          <key> the tag key, for example: "environ" or "rack"
          <value> the tag value, for example: "prod" or "1"

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        body = {}
        body['tags'] = json.dumps(dictify(args['<key>=<value>']))
        sys.stdout.write('Applying tags... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', "/v1/apps/{}/config".format(app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            version = response.headers['x-deis-release']
            self._logger.info("done, v{}\n".format(version))

            self._print_tags(app, response.json())
        else:
            raise ResponseError(response)

    def tags_unset(self, args):
        """
        Unsets tags for an application.

        Usage: deis tags:unset [options] <key>...

        Arguments:
          <key> the tag key to unset, for example: "environ" or "rack"

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        values = {}
        for k in args.get('<key>'):
            values[k] = None
        body = {}
        body['tags'] = json.dumps(values)
        sys.stdout.write('Applying tags... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', "/v1/apps/{}/config".format(app), json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            version = response.headers['x-deis-release']
            self._logger.info("done, v{}\n".format(version))
            self._print_tags(app, response.json())
        else:
            raise ResponseError(response)

    def _print_tags(self, app, config):
        items = config['tags']
        self._logger.info("=== {} Tags".format(app))
        if len(items) == 0:
            self._logger.info('No tags defined')
            return
        keys = sorted(items)
        width = max(map(len, keys)) + 5
        for k in keys:
            v = items[k]
            self._logger.info(("{k:<" + str(width) + "} {v}").format(**locals()))

    def keys(self, args):
        """
        Valid commands for SSH keys:

        keys:list        list SSH keys for the logged in user
        keys:add         add an SSH key
        keys:remove      remove an SSH key

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'keys:list'
        args = docopt(self.keys_list.__doc__)
        return self.keys_list(args)

    def keys_add(self, args):
        """
        Adds SSH keys for the logged in user.

        Usage: deis keys:add [<key>]

        Arguments:
          <key>
            a local file path to an SSH public key used to push application code.
        """
        path = args.get('<key>')
        if not path:
            selected_key = self._ask_pubkey_interactively()
        else:
            # check the specified key format
            selected_key = self._parse_key(path)
        if not selected_key:
            self._logger.error("usage: deis keys:add [<key>]")
            return
        # Upload the key to Deis
        body = {
            'id': selected_key.id,
            'public': "{} {}".format(selected_key.type, selected_key.str)
        }
        sys.stdout.write("Uploading {} to Deis...".format(selected_key.id))
        sys.stdout.flush()
        response = self._dispatch('post', '/v1/keys', json.dumps(body))
        if response.status_code == requests.codes.created:
            self._logger.info('done')
        else:
            raise ResponseError(response)

    def _parse_key(self, path):
        """Parse an SSH public key path into a Key namedtuple."""
        Key = namedtuple('Key', 'path name type str comment id')
        name = path.split(os.path.sep)[-1]
        with open(path) as f:
            data = f.read()
            match = re.match(r'^(ssh-...|ecdsa-[^ ]+) ([^ ]+) ?(.*)',
                             data)
            if not match:
                self._logger.error("Could not parse SSH public key {0}".format(name))
                sys.exit(1)
            key_type, key_str, key_comment = match.groups()
            if key_comment:
                key_id = key_comment
            else:
                key_id = name.replace('.pub', '')
            return Key(path, name, key_type, key_str, key_comment, key_id)

    def _ask_pubkey_interactively(self):
        # find public keys and prompt the user to pick one
        ssh_dir = os.path.expanduser('~/.ssh')
        pubkey_paths = glob.glob(os.path.join(ssh_dir, '*.pub'))
        if not pubkey_paths:
            self._logger.error('No SSH public keys found')
            return
        pubkeys_list = [self._parse_key(k) for k in pubkey_paths]
        self._logger.info('Found the following SSH public keys:')
        for i, key_ in enumerate(pubkeys_list):
            self._logger.info("{}) {} {}".format(i + 1, key_.name, key_.comment))
        self._logger.info("0) Enter path to pubfile (or use keys:add <key_path>) ")
        inp = raw_input('Which would you like to use with Deis? ')
        try:
            if int(inp) != 0:
                selected_key = pubkeys_list[int(inp) - 1]
            else:
                selected_key_path = raw_input('Enter the path to the pubkey file: ')
                selected_key = self._parse_key(os.path.expanduser(selected_key_path))
        except:
            self._logger.info('Aborting')
            return
        return selected_key

    def keys_list(self, args):
        """
        Lists SSH keys for the logged in user.

        Usage: deis keys:list
        """
        response = self._dispatch('get', '/v1/keys')
        if response.status_code == requests.codes.ok:
            data = response.json()
            if data['count'] == 0:
                self._logger.info('No keys found')
                return
            self._logger.info("=== {owner} Keys".format(**data['results'][0]))
            for key in data['results']:
                public = key['public']
                self._logger.info("{0} {1}...{2}".format(
                    key['id'], public[0:16], public[-10:]))
        else:
            raise ResponseError(response)

    def keys_remove(self, args):
        """
        Removes an SSH key for the logged in user.

        Usage: deis keys:remove <key>

        Arguments:
          <key>
            the SSH public key to revoke source code push access.
        """
        key = args.get('<key>')
        sys.stdout.write("Removing {} SSH Key... ".format(key))
        sys.stdout.flush()
        response = self._dispatch('delete', "/v1/keys/{}".format(key))
        if response.status_code == requests.codes.no_content:
            self._logger.info('done')
        else:
            raise ResponseError(response)

    def perms(self, args):
        """
        Valid commands for perms:

        perms:list            list permissions granted on an app
        perms:create          create a new permission for a user
        perms:delete          delete a permission for a user

        Use `deis help perms:[command]` to learn more.
        """
        sys.argv[1] = 'perms:list'
        args = docopt(self.perms_list.__doc__)
        return self.perms_list(args)

    def perms_list(self, args):
        """
        Lists all users with permission to use an app, or lists all users with system
        administrator privileges.

        Usage: deis perms:list [-a --app=<app>|--admin]

        Options:
          -a --app=<app>
            lists all users with permission to <app>. <app> is the uniquely identifiable name
            for the application.

          --admin
            lists all users with system administrator privileges.
        """
        app, url = self._parse_perms_args(args)
        response = self._dispatch('get', url)
        if response.status_code == requests.codes.ok:
            self._logger.info(json.dumps(response.json(), indent=2))
        else:
            raise ResponseError(response)

    def perms_create(self, args):
        """
        Gives another user permission to use an app, or gives another user
        system administrator privileges.

        Usage: deis perms:create <username> [-a --app=<app>|--admin]

        Arguments:
          <username>
            the name of the new user.

        Options:
          -a --app=<app>
            grants <username> permission to use <app>. <app> is the uniquely identifiable name
            for the application.

          --admin
            grants <username> system administrator privileges.
        """
        app, url = self._parse_perms_args(args)
        username = args.get('<username>')
        body = {'username': username}
        if app:
            msg = "Adding {} to {} collaborators... ".format(username, app)
        else:
            msg = "Adding {} to system administrators... ".format(username)
        sys.stdout.write(msg)
        sys.stdout.flush()
        response = self._dispatch('post', url, json.dumps(body))
        if response.status_code == requests.codes.created:
            self._logger.info('done')
        else:
            raise ResponseError(response)

    def perms_delete(self, args):
        """
        Revokes another user's permission to use an app, or revokes another user's system
        administrator privileges.

        Usage: deis perms:delete <username> [-a --app=<app>|--admin]

        Arguments:
          <username>
            the name of the user.

        Options:
          -a --app=<app>
            revokes <username> permission to use <app>. <app> is the uniquely identifiable name
            for the application.

          --admin
            revokes <username> system administrator privileges.
        """
        app, url = self._parse_perms_args(args)
        username = args.get('<username>')
        url = "{}/{}".format(url, username)
        if app:
            msg = "Removing {} from {} collaborators... ".format(username, app)
        else:
            msg = "Remove {} from system administrators... ".format(username)
        sys.stdout.write(msg)
        sys.stdout.flush()
        response = self._dispatch('delete', url)
        if response.status_code == requests.codes.no_content:
            self._logger.info('done')
        else:
            raise ResponseError(response)

    def _parse_perms_args(self, args):
        app = args.get('--app'),
        admin = args.get('--admin')
        if admin:
            app = None
            url = '/v1/admin/perms'
        else:
            app = app[0] or self._session.app
            url = "/v1/apps/{}/perms".format(app)
        return app, url

    def releases(self, args):
        """
        Valid commands for releases:

        releases:list        list an application's release history
        releases:info        print information about a specific release
        releases:rollback    return to a previous release

        Use `deis help [command]` to learn more.
        """
        sys.argv[1] = 'releases:list'
        args = docopt(self.releases_list.__doc__)
        return self.releases_list(args)

    def releases_info(self, args):
        """
        Prints info about a particular release.

        Usage: deis releases:info <version> [options]

        Arguments:
          <version>
            the release of the application, such as 'v1'.

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        version = args.get('<version>')
        if not version.startswith('v'):
            version = 'v' + version
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch(
            'get', "/v1/apps/{app}/releases/{version}".format(**locals()))
        if response.status_code == requests.codes.ok:
            self._logger.info(json.dumps(response.json(), indent=2))
        else:
            raise ResponseError(response)

    def releases_list(self, args):
        """
        Lists release history for an application.

        Usage: deis releases:list [options]

        Options:
          -a --app=<app>
            the uniquely identifiable name for the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        response = self._dispatch('get', "/v1/apps/{app}/releases".format(**locals()))
        if response.status_code == requests.codes.ok:
            self._logger.info("=== {} Releases".format(app))
            data = response.json()
            for item in data['results']:
                item['created'] = readable_datetime(item['created'])
                self._logger.info("v{version:<6} {created:<24} {summary}".format(**item))
        else:
            raise ResponseError(response)

    def releases_rollback(self, args):
        """
        Rolls back to a previous application release.

        Usage: deis releases:rollback [<version>] [options]

        Arguments:
          <version>
            the release of the application, such as 'v1'.

        Options:
          -a --app=<app>
            the uniquely identifiable name of the application.
        """
        app = args.get('--app')
        if not app:
            app = self._session.app
        version = args.get('<version>')
        if version:
            if version.startswith('v'):
                version = version[1:]
            body = {'version': int(version)}
        else:
            body = {}
        url = "/v1/apps/{app}/releases/rollback".format(**locals())
        if version:
            sys.stdout.write('Rolling back to v{version}... '.format(**locals()))
        else:
            sys.stdout.write('Rolling back one release... ')
        sys.stdout.flush()
        try:
            progress = TextProgress()
            progress.start()
            response = self._dispatch('post', url, json.dumps(body))
        finally:
            progress.cancel()
            progress.join()
        if response.status_code == requests.codes.created:
            new_version = response.json()['version']
            self._logger.info("done, v{}".format(new_version))
        else:
            raise ResponseError(response)

    def shortcuts(self, args):
        """
        Shows valid shortcuts for client commands.

        Usage: deis shortcuts
        """
        self._logger.info('Valid shortcuts are:\n')
        for shortcut, command in SHORTCUTS.items():
            if ':' not in shortcut:
                self._logger.info("{:<10} -> {}".format(shortcut, command))
        self._logger.info('\nUse `deis help [command]` to learn more')

SHORTCUTS = OrderedDict([
    ('create', 'apps:create'),
    ('destroy', 'apps:destroy'),
    ('info', 'apps:info'),
    ('login', 'auth:login'),
    ('logout', 'auth:logout'),
    ('logs', 'apps:logs'),
    ('open', 'apps:open'),
    ('passwd', 'auth:passwd'),
    ('pull', 'builds:create'),
    ('register', 'auth:register'),
    ('rollback', 'releases:rollback'),
    ('run', 'apps:run'),
    ('scale', 'ps:scale'),
    ('sharing', 'perms:list'),
    ('sharing:list', 'perms:list'),
    ('sharing:add', 'perms:create'),
    ('sharing:remove', 'perms:delete'),
    ('whoami', 'auth:whoami'),
])


def parse_args(cmd):
    """
    Parses command-line args applying shortcuts and looking for help flags.
    """
    if cmd == 'help':
        cmd = sys.argv[-1]
        help_flag = True
    else:
        cmd = sys.argv[1]
        help_flag = False
    # swap cmd with shortcut
    if cmd in SHORTCUTS:
        cmd = SHORTCUTS[cmd]
        # change the cmdline arg itself for docopt
        if not help_flag:
            sys.argv[1] = cmd
        else:
            sys.argv[2] = cmd
    # convert : to _ for matching method names and docstrings
    if ':' in cmd:
        cmd = '_'.join(cmd.split(':'))
    return cmd, help_flag


def _dispatch_cmd(method, args):
    logger = logging.getLogger(__name__)
    try:
        method(args)
    except requests.exceptions.ConnectionError as err:
        logger.error("Couldn't connect to the Deis Controller. Make sure that the Controller URI is \
correct and the server is running.")
        sys.exit(1)
    except EnvironmentError as err:
        logger.error(err.message)
        sys.exit(1)
    except ResponseError as err:
        resp = err.message
        logger.error('{} {}'.format(resp.status_code, resp.reason))
        try:
            msg = resp.json()
            if 'detail' in msg:
                msg = "Detail:\n{}".format(msg['detail'])
        except:
            msg = resp.text
        logger.info(msg)
        sys.exit(1)


def _init_logger():
    logger = logging.getLogger(__name__)
    handler = logging.StreamHandler(sys.stdout)
    # TODO: add a --debug flag
    logger.setLevel(logging.INFO)
    handler.setLevel(logging.INFO)
    logger.addHandler(handler)


def main():
    """
    Create a client, parse the arguments received on the command line, and
    call the appropriate method on the client.
    """
    _init_logger()
    cli = DeisClient()
    args = docopt(__doc__, version=__version__,
                  options_first=True)
    cmd = args['<command>']
    cmd, help_flag = parse_args(cmd)
    # print help if it was asked for
    if help_flag:
        if cmd != 'help' and cmd in dir(cli):
            print(trim(getattr(cli, cmd).__doc__))
            return
        docopt(__doc__, argv=['--help'])
    # unless cmd needs to use sys.argv directly
    if hasattr(cli, cmd):
        method = getattr(cli, cmd)
    else:
        raise DocoptExit('Found no matching command, try `deis help`')
    # re-parse docopt with the relevant docstring
    docstring = trim(getattr(cli, cmd).__doc__)
    if 'Usage: ' in docstring:
        args.update(docopt(docstring))
    # dispatch the CLI command
    _dispatch_cmd(method, args)


if __name__ == '__main__':
    main()
    sys.exit(0)
