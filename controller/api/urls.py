"""
RESTful URL patterns and routing for the Deis API app.


Applications
============

.. http:get:: /v1/apps/(string:id)/

  Retrieve a :class:`~api.models.App` by its `id`.

.. http:delete:: /v1/apps/(string:id)/

  Destroy a :class:`~api.models.App` by its `id`.

.. http:get:: /v1/apps/

  List all :class:`~api.models.App`\s.

.. http:post:: /v1/apps/

  Create a new :class:`~api.models.App`.


Application Release Components
------------------------------

.. http:get:: /v1/apps/(string:id)/config/

  List all :class:`~api.models.Config`\s.

.. http:post:: /v1/apps/(string:id)/config/

  Create a new :class:`~api.models.Config`.

.. http:get:: /v1/apps/(string:id)/builds/(string:uuid)/

  Retrieve a :class:`~api.models.Build` by its `uuid`.

.. http:get:: /v1/apps/(string:id)/builds/

  List all :class:`~api.models.Build`\s.

.. http:post:: /v1/apps/(string:id)/builds/

  Create a new :class:`~api.models.Build`.

.. http:get:: /v1/apps/(string:id)/releases/(int:version)/

  Retrieve a :class:`~api.models.Release` by its `version`.

.. http:get:: /v1/apps/(string:id)/releases/

  List all :class:`~api.models.Release`\s.

.. http:post:: /v1/apps/(string:id)/releases/rollback/

  Rollback to a previous :class:`~api.models.Release`.


Application Infrastructure
--------------------------

.. http:get:: /v1/apps/(string:id)/containers/(string:type)/(int:num)/

  List all :class:`~api.models.Container`\s.

.. http:get:: /v1/apps/(string:id)/containers/(string:type)/

  List all :class:`~api.models.Container`\s.

.. http:get:: /v1/apps/(string:id)/containers/

  List all :class:`~api.models.Container`\s.


Application Domains
-------------------


.. http:delete:: /v1/apps/(string:id)/domains/(string:hostname)

  Destroy a :class:`~api.models.Domain` by its `hostname`

.. http:get:: /v1/apps/(string:id)/domains/

  List all :class:`~api.models.Domain`\s.

.. http:post:: /v1/apps/(string:id)/domains/

  Create a new :class:`~api.models.Domain`\s.


Application Actions
-------------------

.. http:post:: /v1/apps/(string:id)/scale/

  See also
  :meth:`AppViewSet.scale() <api.views.AppViewSet.scale>`

.. http:get:: /v1/apps/(string:id)/logs/

  See also
  :meth:`AppViewSet.logs() <api.views.AppViewSet.logs>`

.. http:post:: /v1/apps/(string:id)/run/

  See also
  :meth:`AppViewSet.run() <api.views.AppViewSet.run>`


Application Sharing
===================

.. http:delete:: /v1/apps/(string:id)/perms/(string:username)/

  Destroy an app permission by its `username`.

.. http:get:: /v1/apps/(string:id)/perms/

  List all permissions granted to this app.

.. http:post:: /v1/apps/(string:id)/perms/

  Create a new app permission.


Keys
====

.. http:get:: /v1/keys/(string:id)/

  Retrieve a :class:`~api.models.Key` by its `id`.

.. http:delete:: /v1/keys/(string:id)/

  Destroy a :class:`~api.models.Key` by its `id`.

.. http:get:: /v1/keys/

  List all :class:`~api.models.Key`\s.

.. http:post:: /v1/keys/

  Create a new :class:`~api.models.Key`.


API Hooks
=========

.. http:post:: /v1/hooks/push/

  Create a new :class:`~api.models.Push`.

.. http:post:: /v1/hooks/build/

  Create a new :class:`~api.models.Build`.

.. http:post:: /v1/hooks/config/

  Retrieve latest application :class:`~api.models.Config`.


Auth
====

.. http:post:: /v1/auth/register/

  Create a new User.

.. http:delete:: /v1/auth/cancel/

  Destroy the logged-in User.

.. http:post:: /v1/auth/passwd/

  Update the password of the logged-in User.

.. http:get:: /v1/auth/login/

  Generate an API key.


Admin Sharing
=============

.. http:delete:: /v1/admin/perms/(string:username)/

  Destroy an admin permission by its `username`.

.. http:get:: /v1/admin/perms/

  List all admin permissions granted.

.. http:post:: /v1/admin/perms/

  Create a new admin permission.

"""

from __future__ import unicode_literals

from django.conf import settings
from django.conf.urls import include
from django.conf.urls import patterns
from django.conf.urls import url

from api import routers
from api import views


router = routers.ApiRouter()

# Add the generated REST URLs and login/logout endpoint
urlpatterns = patterns(
    '',
    url(r'^', include(router.urls)),
    # application release components
    url(r'^apps/(?P<id>{})/config/?'.format(settings.APP_URL_REGEX),
        views.AppConfigViewSet.as_view({'get': 'retrieve', 'post': 'create'})),
    url(r'^apps/(?P<id>{})/builds/(?P<uuid>[-_\w]+)/?'.format(settings.APP_URL_REGEX),
        views.AppBuildViewSet.as_view({'get': 'retrieve'})),
    url(r'^apps/(?P<id>{})/builds/?'.format(settings.APP_URL_REGEX),
        views.AppBuildViewSet.as_view({'get': 'list', 'post': 'create'})),
    url(r'^apps/(?P<id>{})/releases/v(?P<version>[0-9]+)/?'.format(settings.APP_URL_REGEX),
        views.AppReleaseViewSet.as_view({'get': 'retrieve'})),
    url(r'^apps/(?P<id>{})/releases/rollback/?'.format(settings.APP_URL_REGEX),
        views.AppReleaseViewSet.as_view({'post': 'rollback'})),
    url(r'^apps/(?P<id>{})/releases/?'.format(settings.APP_URL_REGEX),
        views.AppReleaseViewSet.as_view({'get': 'list'})),
    # application infrastructure
    url(r'^apps/(?P<id>{})/containers/(?P<type>[-_\w]+)/(?P<num>[-_\w]+)/?'.format(
        settings.APP_URL_REGEX),
        views.AppContainerViewSet.as_view({'get': 'retrieve'})),
    url(r'^apps/(?P<id>{})/containers/(?P<type>[-_\w.]+)/?'.format(settings.APP_URL_REGEX),
        views.AppContainerViewSet.as_view({'get': 'list'})),
    url(r'^apps/(?P<id>{})/containers/?'.format(settings.APP_URL_REGEX),
        views.AppContainerViewSet.as_view({'get': 'list'})),
    # application domains
    url(r'^apps/(?P<id>{})/domains/(?P<domain>[-\._\w]+)/?'.format(settings.APP_URL_REGEX),
        views.DomainViewSet.as_view({'delete': 'destroy'})),
    url(r'^apps/(?P<id>{})/domains/?'.format(settings.APP_URL_REGEX),
        views.DomainViewSet.as_view({'post': 'create', 'get': 'list'})),
    # application actions
    url(r'^apps/(?P<id>{})/scale/?'.format(settings.APP_URL_REGEX),
        views.AppViewSet.as_view({'post': 'scale'})),
    url(r'^apps/(?P<id>{})/logs/?'.format(settings.APP_URL_REGEX),
        views.AppViewSet.as_view({'get': 'logs'})),
    url(r'^apps/(?P<id>{})/run/?'.format(settings.APP_URL_REGEX),
        views.AppViewSet.as_view({'post': 'run'})),
    # apps sharing
    url(r'^apps/(?P<id>{})/perms/(?P<username>[-_\w]+)/?'.format(settings.APP_URL_REGEX),
        views.AppPermsViewSet.as_view({'delete': 'destroy'})),
    url(r'^apps/(?P<id>{})/perms/?'.format(settings.APP_URL_REGEX),
        views.AppPermsViewSet.as_view({'get': 'list', 'post': 'create'})),
    # apps base endpoint
    url(r'^apps/(?P<id>{})/?'.format(settings.APP_URL_REGEX),
        views.AppViewSet.as_view({'get': 'retrieve', 'delete': 'destroy'})),
    url(r'^apps/?',
        views.AppViewSet.as_view({'get': 'list', 'post': 'create'})),
    # key
    url(r'^keys/(?P<id>.+)/?',
        views.KeyViewSet.as_view({
            'get': 'retrieve', 'delete': 'destroy'})),
    url(r'^keys/?',
        views.KeyViewSet.as_view({'get': 'list', 'post': 'create'})),
    # hooks
    url(r'^hooks/push/?',
        views.PushHookViewSet.as_view({'post': 'create'})),
    url(r'^hooks/build/?',
        views.BuildHookViewSet.as_view({'post': 'create'})),
    url(r'^hooks/config/?',
        views.ConfigHookViewSet.as_view({'post': 'create'})),
    # authn / authz
    url(r'^auth/register/?',
        views.UserRegistrationView.as_view({'post': 'create'})),
    url(r'^auth/cancel/?',
        views.UserManagementView.as_view({'delete': 'destroy'})),
    url(r'^auth/passwd/?',
        views.UserManagementView.as_view({'post': 'passwd'})),
    url(r'^auth/login/',
        'rest_framework.authtoken.views.obtain_auth_token'),
    # admin sharing
    url(r'^admin/perms/(?P<username>[-_\w]+)/?',
        views.AdminPermsViewSet.as_view({'delete': 'destroy'})),
    url(r'^admin/perms/?',
        views.AdminPermsViewSet.as_view({'get': 'list', 'post': 'create'})),
)
