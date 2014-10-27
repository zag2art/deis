"""
Unit tests for the Deis api app.

Run the tests with "./manage.py test api"
"""

from __future__ import unicode_literals

import json
import mock
import os.path
import requests

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TestCase
from rest_framework.authtoken.models import Token

from api.models import App


def mock_import_repository_task(*args, **kwargs):
    resp = requests.Response()
    resp.status_code = 200
    resp._content_consumed = True
    return resp


class AppTest(TestCase):
    """Tests creation of applications"""

    fixtures = ['tests.json']

    def setUp(self):
        self.user = User.objects.get(username='autotest')
        self.token = Token.objects.get(user=self.user).key
        # provide mock authentication used for run commands
        settings.SSH_PRIVATE_KEY = '<some-ssh-private-key>'

    def tearDown(self):
        # reset global vars for other tests
        settings.SSH_PRIVATE_KEY = ''

    def test_app(self):
        """
        Test that a user can create, read, update and delete an application
        """
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']  # noqa
        self.assertIn('id', response.data)
        self.assertIn('url', response.data)
        self.assertEqual(response.data['url'], '{app_id}.deisapp.local'.format(**locals()))
        response = self.client.get('/v1/apps',
                                   HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        url = '/v1/apps/{app_id}'.format(**locals())
        response = self.client.get(url,
                                   HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        body = {'id': 'new'}
        response = self.client.patch(url, json.dumps(body), content_type='application/json',
                                     HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 405)
        response = self.client.delete(url,
                                      HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)

    def test_app_override_id(self):
        body = {'id': 'myid'}
        response = self.client.post('/v1/apps', json.dumps(body),
                                    content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        body = {'id': response.data['id']}
        response = self.client.post('/v1/apps', json.dumps(body),
                                    content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertContains(response, 'App with this Id already exists.', status_code=400)
        return response

    def test_app_actions(self):
        url = '/v1/apps'
        body = {'id': 'autotest'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']  # noqa
        # test logs
        if not os.path.exists(settings.DEIS_LOG_DIR):
            os.mkdir(settings.DEIS_LOG_DIR)
        path = os.path.join(settings.DEIS_LOG_DIR, app_id + '.log')
        # HACK: remove app lifecycle logs
        if os.path.exists(path):
            os.remove(path)
        url = '/v1/apps/{app_id}/logs'.format(**locals())
        response = self.client.get(url,
                                   HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        self.assertEqual(response.data, 'No logs for {}'.format(app_id))
        # write out some fake log data and try again
        with open(path, 'a') as f:
            f.write(FAKE_LOG_DATA)
        response = self.client.get(url,
                                   HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data, FAKE_LOG_DATA)
        os.remove(path)
        # TODO: test run needs an initial build

    def test_app_release_notes_in_logs(self):
        """Verifies that an app's release summary is dumped into the logs."""
        url = '/v1/apps'
        body = {'id': 'autotest'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']  # noqa
        path = os.path.join(settings.DEIS_LOG_DIR, app_id + '.log')
        url = '/v1/apps/{app_id}/logs'.format(**locals())
        response = self.client.get(url,
                                   HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertIn('autotest created initial release', response.data)
        self.assertEqual(response.status_code, 200)
        # delete file for future runs
        os.remove(path)

    def test_app_errors(self):
        app_id = 'autotest-errors'
        url = '/v1/apps'
        body = {'id': 'camelCase'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertContains(response, 'App IDs can only contain [a-z0-9-]', status_code=400)
        url = '/v1/apps'
        body = {'id': 'deis'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertContains(response, "App IDs cannot be 'deis'", status_code=400)
        body = {'id': app_id}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']  # noqa
        url = '/v1/apps/{app_id}'.format(**locals())
        response = self.client.delete(url,
                                      HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEquals(response.status_code, 204)
        for endpoint in ('containers', 'config', 'releases', 'builds'):
            url = '/v1/apps/{app_id}/{endpoint}'.format(**locals())
            response = self.client.get(url,
                                       HTTP_AUTHORIZATION='token {}'.format(self.token))
            self.assertEquals(response.status_code, 404)

    def test_app_structure_is_valid_json(self):
        """Application structures should be valid JSON objects."""
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        self.assertIn('structure', response.data)
        self.assertEqual(response.data['structure'], {})
        app = App.objects.get(id=app_id)
        app.structure = {'web': 1}
        app.save()
        url = '/v1/apps/{}'.format(app_id)
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertIn('structure', response.data)
        self.assertEqual(response.data['structure'], {"web": 1})

    @mock.patch('requests.post', mock_import_repository_task)
    def test_admin_can_manage_other_apps(self):
        """Administrators of Deis should be able to manage all applications.
        """
        # log in as non-admin user and create an app
        user = User.objects.get(username='autotest2')
        token = Token.objects.get(user=user)
        app_id = 'autotest'
        url = '/v1/apps'
        body = {'id': app_id}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(token))
        app = App.objects.get(id=app_id)
        # log in as admin, check to see if they have access
        url = '/v1/apps/{}'.format(app_id)
        response = self.client.get(url,
                                   HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        # check app logs
        url = '/v1/apps/{app_id}/logs'.format(**locals())
        response = self.client.get(url,
                                   HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertIn('autotest2 created initial release', response.data)
        # TODO: test run needs an initial build
        # delete the app
        url = '/v1/apps/{}'.format(app_id)
        response = self.client.delete(url,
                                      HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)

    def test_admin_can_see_other_apps(self):
        """If a user creates an application, the administrator should be able
        to see it.
        """
        # log in as non-admin user and create an app
        user = User.objects.get(username='autotest2')
        token = Token.objects.get(user=user)
        app_id = 'autotest'
        url = '/v1/apps'
        body = {'id': app_id}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(token))
        # log in as admin
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.data['count'], 1)

    def test_run_without_auth(self):
        """If the administrator has not provided SSH private key for run commands,
        make sure a friendly error message is provided on run"""
        settings.SSH_PRIVATE_KEY = ''
        url = '/v1/apps'
        body = {'id': 'autotest'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']  # noqa
        # test run
        url = '/v1/apps/{app_id}/run'.format(**locals())
        body = {'command': 'ls -al'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEquals(response.status_code, 400)
        self.assertEquals(response.data, 'Support for admin commands is not configured')

    def test_run_without_release_should_error(self):
        """
        A user should not be able to run a one-off command unless a release
        is present.
        """
        app_id = 'autotest'
        url = '/v1/apps'
        body = {'id': app_id}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        url = '/v1/apps/{}/run'.format(app_id)
        body = {'command': 'ls -al'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, "No build associated with this release "
                                        "to run this command")


FAKE_LOG_DATA = """
2013-08-15 12:41:25 [33454] [INFO] Starting gunicorn 17.5
2013-08-15 12:41:25 [33454] [INFO] Listening at: http://0.0.0.0:5000 (33454)
2013-08-15 12:41:25 [33454] [INFO] Using worker: sync
2013-08-15 12:41:25 [33457] [INFO] Booting worker with pid 33457
"""
