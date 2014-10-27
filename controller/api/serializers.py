"""
Classes to serialize the RESTful representation of Deis API models.
"""

from __future__ import unicode_literals

import json
import re

from django.conf import settings
from django.contrib.auth.models import User
from rest_framework import serializers

from api import models
from api import utils


PROCTYPE_MATCH = re.compile(r'^(?P<type>[a-z]+)')
MEMLIMIT_MATCH = re.compile(r'^(?P<mem>[0-9]+[BbKkMmGg])$')
CPUSHARE_MATCH = re.compile(r'^(?P<cpu>[0-9]+)$')
TAGKEY_MATCH = re.compile(r'^[a-z]+$')
TAGVAL_MATCH = re.compile(r'^\w+$')


class OwnerSlugRelatedField(serializers.SlugRelatedField):
    """Filter queries by owner as well as slug_field."""

    def from_native(self, data):
        """Fetch model object from its 'native' representation.
        TODO: request.user is not going to work in a team environment...
        """
        self.queryset = self.queryset.filter(owner=self.context['request'].user)
        return serializers.SlugRelatedField.from_native(self, data)


class JSONFieldSerializer(serializers.WritableField):
    def to_native(self, obj):
        return obj

    def from_native(self, value):
        try:
            val = json.loads(value)
        except TypeError:
            val = value
        return val


class UserSerializer(serializers.ModelSerializer):
    """Serialize a User model."""

    class Meta:
        """Metadata options for a UserSerializer."""
        model = User
        read_only_fields = ('is_superuser', 'is_staff', 'groups',
                            'user_permissions', 'last_login', 'date_joined')

    @property
    def data(self):
        """Custom data property that removes secure user fields"""
        d = super(UserSerializer, self).data
        for f in ('password',):
            if f in d:
                del d[f]
        return d


class AdminUserSerializer(serializers.ModelSerializer):
    """Serialize admin status for a User model."""

    class Meta:
        model = User
        fields = ('username', 'is_superuser')
        read_only_fields = ('username',)


class AppSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.App` model."""

    owner = serializers.Field(source='owner.username')
    id = serializers.SlugField(default=utils.generate_app_name)
    url = serializers.Field(source='url')
    structure = JSONFieldSerializer(source='structure', required=False)
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a :class:`AppSerializer`."""
        model = models.App

    def validate_id(self, attrs, source):
        """
        Check that the ID is all lowercase and not 'deis'
        """
        value = attrs[source]
        match = re.match(r'^[a-z0-9-]+$', value)
        if not match:
            raise serializers.ValidationError("App IDs can only contain [a-z0-9-]")
        if value == 'deis':
            raise serializers.ValidationError("App IDs cannot be 'deis'")
        return attrs


class BuildSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.Build` model."""

    owner = serializers.Field(source='owner.username')
    app = serializers.SlugRelatedField(slug_field='id')
    procfile = JSONFieldSerializer(source='procfile', required=False)
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a :class:`BuildSerializer`."""
        model = models.Build
        read_only_fields = ('uuid',)


class ConfigSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.Config` model."""

    owner = serializers.Field(source='owner.username')
    app = serializers.SlugRelatedField(slug_field='id')
    values = JSONFieldSerializer(source='values', required=False)
    memory = JSONFieldSerializer(source='memory', required=False)
    cpu = JSONFieldSerializer(source='cpu', required=False)
    tags = JSONFieldSerializer(source='tags', required=False)
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a :class:`ConfigSerializer`."""
        model = models.Config
        read_only_fields = ('uuid',)

    def validate_memory(self, attrs, source):
        for k, v in attrs.get(source, {}).items():
            if v is None:  # use NoneType to unset a value
                continue
            if not re.match(PROCTYPE_MATCH, k):
                raise serializers.ValidationError("Process types can only contain [a-z]")
            if not re.match(MEMLIMIT_MATCH, str(v)):
                raise serializers.ValidationError(
                    "Limit format: <number><unit>, where unit = B, K, M or G")
        return attrs

    def validate_cpu(self, attrs, source):
        for k, v in attrs.get(source, {}).items():
            if v is None:  # use NoneType to unset a value
                continue
            if not re.match(PROCTYPE_MATCH, k):
                raise serializers.ValidationError("Process types can only contain [a-z]")
            shares = re.match(CPUSHARE_MATCH, str(v))
            if not shares:
                raise serializers.ValidationError("CPU shares must be an integer")
            for v in shares.groupdict().values():
                try:
                    i = int(v)
                except ValueError:
                    raise serializers.ValidationError("CPU shares must be an integer")
                if i > 1024 or i < 0:
                    raise serializers.ValidationError("CPU shares must be between 0 and 1024")
        return attrs

    def validate_tags(self, attrs, source):
        for k, v in attrs.get(source, {}).items():
            if v is None:  # use NoneType to unset a value
                continue
            if not re.match(TAGKEY_MATCH, k):
                raise serializers.ValidationError("Tag keys can only contain [a-z]")
            if not re.match(TAGVAL_MATCH, str(v)):
                raise serializers.ValidationError("Invalid tag value")
        return attrs


class ReleaseSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.Release` model."""

    owner = serializers.Field(source='owner.username')
    app = serializers.SlugRelatedField(slug_field='id')
    config = serializers.SlugRelatedField(slug_field='uuid')
    build = serializers.SlugRelatedField(slug_field='uuid')
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a :class:`ReleaseSerializer`."""
        model = models.Release
        read_only_fields = ('uuid',)


class ContainerSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.Container` model."""

    owner = serializers.Field(source='owner.username')
    app = OwnerSlugRelatedField(slug_field='id')
    release = serializers.SlugRelatedField(slug_field='uuid')
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a :class:`ContainerSerializer`."""
        model = models.Container

    def transform_release(self, obj, value):
        return "v{}".format(obj.release.version)


class KeySerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.Key` model."""

    owner = serializers.Field(source='owner.username')
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a KeySerializer."""
        model = models.Key


class DomainSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.Domain` model."""

    owner = serializers.Field(source='owner.username')
    app = serializers.SlugRelatedField(slug_field='id')
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a :class:`DomainSerializer`."""
        model = models.Domain
        fields = ('domain', 'owner', 'created', 'updated', 'app')

    def validate_domain(self, attrs, source):
        """
        Check that the hostname is valid
        """
        value = attrs[source]
        match = re.match(
            r'^(\*\.)?(' + settings.APP_URL_REGEX + r'\.)*([a-z0-9-]+)\.([a-z0-9]{2,})$',
            value)
        if not match:
            raise serializers.ValidationError(
                "Hostname does not look like a valid hostname. "
                "Only lowercase characters are allowed.")

        if models.Domain.objects.filter(domain=value).exists():
            raise serializers.ValidationError(
                "The domain {} is already in use by another app".format(value))

        domain_parts = value.split('.')
        if domain_parts[0] == '*':
            raise serializers.ValidationError(
                "Adding a wildcard subdomain is currently not supported".format(value))

        return attrs


class PushSerializer(serializers.ModelSerializer):
    """Serialize a :class:`~api.models.Push` model."""

    owner = serializers.Field(source='owner.username')
    app = serializers.SlugRelatedField(slug_field='id')
    created = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)
    updated = serializers.DateTimeField(format=settings.DEIS_DATETIME_FORMAT, read_only=True)

    class Meta:
        """Metadata options for a :class:`PushSerializer`."""
        model = models.Push
        read_only_fields = ('uuid',)
