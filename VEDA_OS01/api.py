"""
Pipeline API METHODS

1. cheap-o token authorizer
This is a super hacky way to finish the Oauth2 Flow, but I need to move on
will get the token id from a url view, auth it, then push forward with a success bool

"""

import os
import sys

from oauth2_provider.models import AccessToken

from rest_framework.authtoken.models import Token
from django.contrib.auth.models import User
from django.core.exceptions import ObjectDoesNotExist


primary_directory = os.path.dirname(__file__)
sys.path.append(primary_directory)


def token_finisher(token_id):
    try:
        d = AccessToken.objects.get(token=token_id)
    except:
        return False

    d.user = User.objects.get(pk=1)
    d.save()

    # https://github.com/armbox/edux/issues/70
    # WARN: possible security issue due to not refreshing token
    try:
        token = Token.objects.get(user=d.user)
    except ObjectDoesNotExist:
        token = Token.objects.create(user=d.user)

    return token.key
