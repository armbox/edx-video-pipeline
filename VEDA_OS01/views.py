"""views"""

import json
import logging
import requests

from django.http import HttpResponse
from django.http import HttpResponseRedirect
from django.views.decorators.csrf import csrf_exempt

from rest_framework import filters, renderers, status, viewsets
from rest_framework.decorators import detail_route
from rest_framework.response import Response
from rest_framework.views import APIView

from api import token_finisher

from VEDA import utils
from VEDA_OS01.models import Course, Video, URL, Encode, TranscriptCredentials, TranscriptProvider
from VEDA_OS01.serializers import CourseSerializer, EncodeSerializer, VideoSerializer, URLSerializer
from VEDA_OS01.transcripts import CIELO24_API_VERSION


LOGGER = logging.getLogger(__name__)


CONFIG = utils.get_config()
CIELO24_LOGIN_URL = utils.build_url(
    CONFIG['cielo24_api_base_url'],
    '/account/login'
)

class CourseViewSet(viewsets.ModelViewSet):

    queryset = Course.objects.all()
    serializer_class = CourseSerializer
    filter_backends = (filters.DjangoFilterBackend,)
    filter_fields = (
        'institution',
        'edx_classid',
        'proc_loc',
        'course_hold',
        'sg_projID'
    )

    @detail_route(renderer_classes=[renderers.StaticHTMLRenderer])
    def highlight(self, request, *args, **kwargs):
        course = self.get_object()
        return Response(course.highlighted)

    @csrf_exempt
    def perform_create(self, serializer):
        serializer.save()


class VideoViewSet(viewsets.ModelViewSet):

    queryset = Video.objects.all()
    serializer_class = VideoSerializer
    filter_backends = (filters.DjangoFilterBackend,)
    filter_fields = ('inst_class', 'edx_id')

    @detail_route(renderer_classes=[renderers.StaticHTMLRenderer])
    def highlight(self, request, *args, **kwargs):
        video = self.get_object()
        return Response(video.highlighted)

    @csrf_exempt
    def perform_create(self, serializer):
        serializer.save()


class EncodeViewSet(viewsets.ModelViewSet):

    queryset = Encode.objects.all()
    serializer_class = EncodeSerializer
    filter_backends = (filters.DjangoFilterBackend,)
    filter_fields = ('encode_filetype', 'encode_suffix', 'product_spec')

    @detail_route(renderer_classes=[renderers.StaticHTMLRenderer])
    def highlight(self, request, *args, **kwargs):
        encode = self.get_object()
        return Response(encode.highlighted)

    @csrf_exempt
    def perform_create(self, serializer):
        serializer.save()


class URLViewSet(viewsets.ModelViewSet):

    queryset = URL.objects.all()
    serializer_class = URLSerializer
    filter_backends = (filters.DjangoFilterBackend,)
    filter_fields = (
        'videoID__edx_id',
        'encode_profile__encode_suffix',
        'encode_profile__encode_filetype'
    )

    @detail_route(renderer_classes=[renderers.StaticHTMLRenderer])
    def highlight(self, request, *args, **kwargs):
        url = self.get_object()
        return Response(url.highlighted)

    @csrf_exempt
    def perform_create(self, serializer):
        serializer.save()


class TranscriptCredentialsView(APIView):
    """
    A Transcript credentials View, used by platform to create/update transcript credentials.
    """

    def get_cielo_token_response(self, username, api_secure_key):
        """
        Returns Cielo24 api token.

        Arguments:
            username(str): Cielo24 username
            api_securekey(str): Cielo24 api key

        Returns:
            Response : Http response object
        """
        return requests.get(CIELO24_LOGIN_URL, params={
            'v': CIELO24_API_VERSION,
            'username': username,
            'securekey': api_secure_key
        })

    def get_api_token(self, username, api_key):
        """
        Returns api token if valid credentials are provided.
        """
        response = self.get_cielo_token_response(username=username, api_secure_key=api_key)
        if not response.ok:
            api_token = None
            LOGGER.warning(
                '[Transcript Credentials] Unable to get api token --  response %s --  status %s.',
                response.text,
                response.status_code,
            )
        else:
            api_token = json.loads(response.content)['ApiToken']
        
        return api_token

    def validate_missing_attributes(self, provider, attributes, credentials):
        """
        Returns error message if provided attributes are not presents in credentials.
        """
        error_message = None
        missing = [attr for attr in attributes if attr not in credentials]
        if missing:
            error_message = u'{missing} must be specified for {provider}.'.format(
                provider=provider,
                missing=' and '.join(missing)
            )

        return error_message

    def validate_transcript_credentials(self, provider, **credentials):
        """
        Validates transcript credentials.

        Validations:
            Providers must be either 3PlayMedia or Cielo24.
            In case of:
                3PlayMedia - 'api_key' and 'api_secret_key' are required.
                Cielo24 - Valid 'api_key' and 'username' are required.
        """
        error_message, validated_credentials = '', {}
        if provider in [TranscriptProvider.CIELO24, TranscriptProvider.THREE_PLAY]:
            if provider == TranscriptProvider.CIELO24:
                must_have_props = ('org', 'api_key', 'username')
                error_message = self.validate_missing_attributes(provider, must_have_props, credentials)

                if not error_message:
                    # Get cielo api token and store it in api_key.
                    api_token = self.get_api_token(credentials['username'], credentials['api_key'])
                    if api_token:
                        validated_credentials.update({
                            'org': credentials['org'],
                            'api_key': api_token
                        })
                    else:
                        error_message = u'Invalid credentials supplied.'
            else:
                must_have_props = ('org', 'api_key', 'api_secret_key')
                error_message = self.validate_missing_attributes(provider, must_have_props, credentials)
                if not error_message:
                    validated_credentials.update({
                        'org': credentials['org'],
                        'api_key': credentials['api_key'],
                        'api_secret': credentials['api_secret_key']
                    })
        else:
            error_message = u'Invalid provider {provider}.'.format(provider=provider)

        return error_message, validated_credentials

    def post(self, request):
        """
        Creates or updates the org-specific transcript credentials with the given information.

        Arguments:
            request: A WSGI request.

        **Example Request**

            POST /api/transcript_credentials {
                "provider": "3PlayMedia",
                "org": "test.x",
                "api_key": "test-api-key",
                "api_secret_key": "test-api-secret-key"
            }

        **POST Parameters**

            A POST request can include the following parameters.

            * provider: A string representation of provider.

            * org: A string representing the organizaton code.
            
            * api_key: A string representing the provider api key.

            * api_secret_key: (Required for 3Play only). A string representing the api secret key.

            * username: (Required for Cielo only). A string representing the cielo username.

            **Example POST Response**

            In case of success:
                Returns an empty response with 201 status code (HTTP 201 Created).

            In case of error:
                Return response with error message and 400 status code (HTTP 400 Bad Request).
                {
                    "message": "Error message."
                }
        """
        # Validate credentials
        provider = request.data.pop('provider', None)
        error_message, validated_credentials = self.validate_transcript_credentials(provider=provider, **request.data)
        if error_message:
            return Response(
                status=status.HTTP_400_BAD_REQUEST,
                data=dict(message=error_message)
            )

        TranscriptCredentials.objects.update_or_create(
            org=validated_credentials.pop('org'), provider=provider, defaults=validated_credentials
        )

        return Response(status=status.HTTP_201_CREATED)


@csrf_exempt
def token_auth(request):
    """

    This is a hack to override the "Authorize" step in token generation

    """
    if request.method == 'POST':
        complete = token_finisher(request.POST['data'])
        return HttpResponse(complete)
    else:
        return HttpResponse(status=404)


def user_login(request):
    if request.user.is_authenticated():
        return HttpResponseRedirect(request.path)
    else:
        return HttpResponseRedirect('../admin')  # settings.LOGIN_REDIRECT_URL)
