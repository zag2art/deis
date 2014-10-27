"""
Unit tests for the Deis api app.

Run the tests with "./manage.py test api"
"""

from __future__ import unicode_literals

import json
import mock
import requests

from django.contrib.auth.models import User
from django.test import TransactionTestCase
from django_fsm import TransitionNotAllowed
from rest_framework.authtoken.models import Token

from api.models import App, Build, Container, Release


def mock_import_repository_task(*args, **kwargs):
    resp = requests.Response()
    resp.status_code = 200
    resp._content_consumed = True
    return resp


class ContainerTest(TransactionTestCase):
    """Tests creation of containers on nodes"""

    fixtures = ['tests.json']

    def setUp(self):
        self.user = User.objects.get(username='autotest')
        self.token = Token.objects.get(user=self.user).key

    def test_container_state_good(self):
        """Test that the finite state machine transitions with a good scheduler"""
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        app = App.objects.get(id=app_id)
        user = User.objects.get(username='autotest')
        build = Build.objects.create(owner=user, app=app, image="qwerty")
        # create an initial release
        release = Release.objects.create(version=2,
                                         owner=user,
                                         app=app,
                                         config=app.config_set.latest(),
                                         build=build)
        # create a container
        c = Container.objects.create(owner=user,
                                     app=app,
                                     release=release,
                                     type='web',
                                     num=1)
        self.assertEqual(c.state, 'initialized')
        # test an illegal transition
        self.assertRaises(TransitionNotAllowed, lambda: c.start())
        c.create()
        self.assertEqual(c.state, 'created')
        c.start()
        self.assertEqual(c.state, 'up')
        c.destroy()
        self.assertEqual(c.state, 'destroyed')

    def test_container_state_protected(self):
        """Test that you cannot directly modify the state"""
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        app = App.objects.get(id=app_id)
        user = User.objects.get(username='autotest')
        build = Build.objects.create(owner=user, app=app, image="qwerty")
        # create an initial release
        release = Release.objects.create(version=2,
                                         owner=user,
                                         app=app,
                                         config=app.config_set.latest(),
                                         build=build)
        # create a container
        c = Container.objects.create(owner=user,
                                     app=app,
                                     release=release,
                                     type='web',
                                     num=1)
        self.assertRaises(AttributeError, lambda: setattr(c, 'state', 'up'))

    def test_container_api_heroku(self):
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # should start with zero
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'sha': 'a'*40,
                'procfile': json.dumps({'web': 'node server.js', 'worker': 'node worker.js'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 4, 'worker': 2}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 6)
        url = "/v1/apps/{app_id}".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        # test listing/retrieving container info
        url = "/v1/apps/{app_id}/containers/web".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 4)
        num = response.data['results'][0]['num']
        url = "/v1/apps/{app_id}/containers/web/{num}".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(response.data['num'], num)
        # scale down
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 2, 'worker': 1}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 3)
        self.assertEqual(max(c['num'] for c in response.data['results']), 2)
        url = "/v1/apps/{app_id}".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        # scale down to 0
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 0, 'worker': 0}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)
        url = "/v1/apps/{app_id}".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)

    @mock.patch('requests.post', mock_import_repository_task)
    def test_container_api_docker(self):
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # should start with zero
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'dockerfile': "FROM busybox\nCMD /bin/true"}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'cmd': 6}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 6)
        url = "/v1/apps/{app_id}".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        # test listing/retrieving container info
        url = "/v1/apps/{app_id}/containers/cmd".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 6)
        # scale down
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'cmd': 3}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 3)
        self.assertEqual(max(c['num'] for c in response.data['results']), 3)
        url = "/v1/apps/{app_id}".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        # scale down to 0
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'cmd': 0}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)
        url = "/v1/apps/{app_id}".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)

    @mock.patch('requests.post', mock_import_repository_task)
    def test_container_release(self):
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # should start with zero
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'sha': 'a'*40,
                'procfile': json.dumps({'web': 'node server.js', 'worker': 'node worker.js'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 1}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['release'], 'v2')
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        self.assertEqual(response.data['image'], body['image'])
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['release'], 'v3')
        # post new config
        url = "/v1/apps/{app_id}/config".format(**locals())
        body = {'values': json.dumps({'KEY': 'value'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        self.assertEqual(response.data['results'][0]['release'], 'v4')

    def test_container_errors(self):
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # create a release so we can scale
        app = App.objects.get(id=app_id)
        user = User.objects.get(username='autotest')
        build = Build.objects.create(owner=user, app=app, image="qwerty")
        # create an initial release
        Release.objects.create(version=2,
                               owner=user,
                               app=app,
                               config=app.config_set.latest(),
                               build=build)
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 'not_an_int'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertContains(response, 'Invalid scaling format', status_code=400)
        body = {'invalid': 1}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertContains(response, 'Container type invalid', status_code=400)

    def test_container_str(self):
        """Test the text representation of a container."""
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'sha': 'a'*40,
                'procfile': json.dumps({'web': 'node server.js', 'worker': 'node worker.js'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 4, 'worker': 2}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        # should start with zero
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 6)
        uuid = response.data['results'][0]['uuid']
        container = Container.objects.get(uuid=uuid)
        self.assertEqual(container.short_name(),
                         "{}.{}.{}".format(container.app, container.type, container.num))
        self.assertEqual(str(container),
                         "{}.{}.{}".format(container.app, container.type, container.num))

    def test_container_command_format(self):
        # regression test for https://github.com/deis/deis/pull/1285
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'sha': 'a'*40,
                'procfile': json.dumps({'web': 'node server.js', 'worker': 'node worker.js'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 1}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        # verify that the container._command property got formatted
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        uuid = response.data['results'][0]['uuid']
        container = Container.objects.get(uuid=uuid)
        self.assertNotIn('{c_type}', container._command)

    def test_container_scale_errors(self):
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # should start with zero
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 0)
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'sha': 'a'*40,
                'procfile': json.dumps({'web': 'node server.js', 'worker': 'node worker.js'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 201)
        # scale to a negative number
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': -1}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 400)
        # scale to something other than a number
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 'one'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 400)
        # scale to something other than a number
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': [1]}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 400)
        # scale up to an integer as a sanity check
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 1}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)

    def test_admin_can_manage_other_containers(self):
        """If a non-admin user creates a container, an administrator should be able to
        manage it.
        """
        user = User.objects.get(username='autotest2')
        token = Token.objects.get(user=user).key
        url = '/v1/apps'
        response = self.client.post(url, HTTP_AUTHORIZATION='token {}'.format(token))
        self.assertEqual(response.status_code, 201)
        app_id = response.data['id']
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'sha': 'a'*40,
                'procfile': json.dumps({'web': 'node server.js', 'worker': 'node worker.js'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(token))
        self.assertEqual(response.status_code, 201)
        # login as admin, scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 4, 'worker': 2}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)

    def test_scale_without_build_should_error(self):
        """A user should not be able to scale processes unless a build is present."""
        app_id = 'autotest'
        url = '/v1/apps'
        body = {'cluster': 'autotest', 'id': app_id}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        url = '/v1/apps/{app_id}/scale'.format(**locals())
        body = {'web': '1'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 400)
        self.assertEqual(response.data, "No build associated with this release")
