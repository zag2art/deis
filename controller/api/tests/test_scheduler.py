"""
Unit tests for the Deis api app.

Run the tests with "./manage.py test api"
"""

from __future__ import unicode_literals

import json

from django.conf import settings
from django.contrib.auth.models import User
from django.test import TransactionTestCase
from rest_framework.authtoken.models import Token

from scheduler import chaos


class SchedulerTest(TransactionTestCase):
    """Tests creation of containers on nodes"""

    fixtures = ['tests.json']

    def setUp(self):
        self.user = User.objects.get(username='autotest')
        self.token = Token.objects.get(user=self.user).key
        # start without any chaos
        chaos.CREATE_ERROR_RATE = 0
        chaos.DESTROY_ERROR_RATE = 0
        chaos.START_ERROR_RATE = 0
        chaos.STOP_ERROR_RATE = 0
        # use chaos scheduler
        settings.SCHEDULER_MODULE = 'chaos'
        # provide mock authentication used for run commands
        settings.SSH_PRIVATE_KEY = '<some-ssh-private-key>'

    def tearDown(self):
        # reset for subsequent tests
        settings.SCHEDULER_MODULE = 'mock'
        settings.SSH_PRIVATE_KEY = ''

    def test_create_chaos(self):
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
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # scale to zero for consistency
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 0}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        # let's get chaotic
        chaos.CREATE_ERROR_RATE = 0.5
        # scale up but expect a 503
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 20}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 503)
        # inspect broken containers
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 20)
        # make sure some failed
        states = set([c['state'] for c in response.data['results']])
        self.assertEqual(states, set(['error', 'created']))

    def test_start_chaos(self):
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
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # scale to zero for consistency
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 0}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        # let's get chaotic
        chaos.START_ERROR_RATE = 0.5
        # scale up, which will allow some crashed containers
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 20}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        # inspect broken containers
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 20)
        # make sure some failed
        states = set([c['state'] for c in response.data['results']])
        self.assertEqual(states, set(['crashed', 'up']))

    def test_destroy_chaos(self):
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
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 20}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 20)
        # let's get chaotic
        chaos.DESTROY_ERROR_RATE = 0.5
        # scale to zero but expect a 503
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 0}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 503)
        # inspect broken containers
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        states = set([c['state'] for c in response.data['results']])
        self.assertEqual(states, set(['error']))
        # make sure we can cleanup after enough tries
        containers = 20
        for _ in range(100):
            url = "/v1/apps/{app_id}/scale".format(**locals())
            body = {'web': 0}
            response = self.client.post(url, json.dumps(body), content_type='application/json',
                                        HTTP_AUTHORIZATION='token {}'.format(self.token))
            # break if we destroyed successfully
            if response.status_code == 204:
                break
            self.assertEquals(response.status_code, 503)
            # inspect broken containers
            url = "/v1/apps/{app_id}/containers".format(**locals())
            response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
            self.assertEqual(response.status_code, 200)
            containers = len(response.data['results'])

    def test_build_chaos(self):
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
        # inspect builds
        url = "/v1/apps/{app_id}/builds".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # inspect releases
        url = "/v1/apps/{app_id}/releases".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 20}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        # simulate failing to create containers
        chaos.CREATE_ERROR_RATE = 0.5
        chaos.START_ERROR_RATE = 0.5
        # post a new build
        url = "/v1/apps/{app_id}/builds".format(**locals())
        body = {'image': 'autotest/example', 'sha': 'b'*40,
                'procfile': json.dumps({'web': 'node server.js', 'worker': 'node worker.js'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 503)
        # inspect releases
        url = "/v1/apps/{app_id}/releases".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
        # inspect containers
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 20)

        # make sure all old containers are still up
        states = set([c['state'] for c in response.data['results']])
        self.assertEqual(states, set(['up']))

    def test_config_chaos(self):
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
        # inspect releases
        url = "/v1/apps/{app_id}/releases".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # scale up
        url = "/v1/apps/{app_id}/scale".format(**locals())
        body = {'web': 20}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 204)
        # simulate failing to create or start containers
        chaos.CREATE_ERROR_RATE = 0.5
        chaos.START_ERROR_RATE = 0.5
        # post a new config
        url = "/v1/apps/{app_id}/config".format(**locals())
        body = {'values': json.dumps({'NEW_URL1': 'http://localhost:8080/'})}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 503)
        # inspect releases
        url = "/v1/apps/{app_id}/releases".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
        # inspect containers
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 20)
        # make sure all old containers are still up
        states = set([c['state'] for c in response.data['results']])
        self.assertEqual(states, set(['up']))

    def test_run_chaos(self):
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
        # inspect builds
        url = "/v1/apps/{app_id}/builds".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # inspect releases
        url = "/v1/apps/{app_id}/releases".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 2)
        url = "/v1/apps/{app_id}/containers".format(**locals())
        response = self.client.get(url, HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 200)
        self.assertEqual(len(response.data['results']), 1)
        # block all create operations
        chaos.CREATE_ERROR_RATE = 1
        # make sure the run fails with a 503
        url = '/v1/apps/{app_id}/run'.format(**locals())
        body = {'command': 'ls -al'}
        response = self.client.post(url, json.dumps(body), content_type='application/json',
                                    HTTP_AUTHORIZATION='token {}'.format(self.token))
        self.assertEqual(response.status_code, 503)
