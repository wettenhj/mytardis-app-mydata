# api.py
"""
Additions to MyTardis's REST API
"""
import logging
import traceback
from datetime import datetime

from django.conf import settings
from django.contrib.sites.models import Site
from tastypie import fields
from tastypie.constants import ALL_WITH_RELATIONS
from ipware.ip import get_ip

import tardis.tardis_portal.api
from tardis.tardis_portal.models.facility import facilities_managed_by
from tardis.tardis_portal.models.experiment import Experiment
from tardis.tardis_portal.models.parameters import Schema
from tardis.tardis_portal.models.parameters import ParameterName
from tardis.tardis_portal.models.parameters import ExperimentParameter
from tardis.tardis_portal.models.parameters import ExperimentParameterSet

from models.uploader import Uploader
from models.uploader import UploaderRegistrationRequest

logger = logging.getLogger(__name__)


class ACLAuthorization(tardis.tardis_portal.api.ACLAuthorization):
    '''Authorisation class for Tastypie.
    '''
    def read_list(self, object_list, bundle):  # noqa # too complex
        authuser = bundle.request.user
        authenticated = authuser.is_authenticated()
        is_facility_manager = authenticated and \
            len(facilities_managed_by(authuser)) > 0
        if isinstance(bundle.obj, Uploader):
            if is_facility_manager:
                return object_list
            return []
        elif isinstance(bundle.obj, UploaderRegistrationRequest):
            if is_facility_manager:
                return object_list
            return []
        else:
            return super(ACLAuthorization, self).read_list(object_list, bundle)

    def read_detail(self, object_list, bundle):  # noqa # too complex
        authuser = bundle.request.user
        authenticated = authuser.is_authenticated()
        is_facility_manager = authenticated and \
            len(facilities_managed_by(authuser)) > 0
        if isinstance(bundle.obj, Uploader):
            return is_facility_manager
        elif isinstance(bundle.obj, UploaderRegistrationRequest):
            return is_facility_manager
        else:
            return super(ACLAuthorization, self).read_detail(object_list,
                                                             bundle)

    def create_list(self, object_list, bundle):
        return super(ACLAuthorization, self).create_list(object_list, bundle)

    def create_detail(self, object_list, bundle):
        if bundle.request.user.is_authenticated() and \
                isinstance(bundle.obj, Uploader):
            return True
        elif bundle.request.user.is_authenticated() and \
                isinstance(bundle.obj, UploaderRegistrationRequest):
            return True
        return super(ACLAuthorization, self).create_detail(object_list, bundle)

    def update_list(self, object_list, bundle):
        return super(ACLAuthorization, self).update_list(object_list, bundle)

    def update_detail(self, object_list, bundle):
        '''
        Uploaders should only be able to update
        the uploader record whose MAC address
        matches theirs (if it exists).
        '''
        if bundle.request.user.is_authenticated() and \
                isinstance(bundle.obj, Uploader):
            return bundle.data['mac_address'] == bundle.obj.mac_address
        return super(ACLAuthorization, self).update_detail(object_list, bundle)

    def delete_list(self, object_list, bundle):
        return super(ACLAuthorization, self).delete_list(object_list, bundle)

    def delete_detail(self, object_list, bundle):
        return super(ACLAuthorization, self).delete_detail(object_list, bundle)


class UploaderAppResource(tardis.tardis_portal.api.MyTardisModelResource):
    instruments = \
        fields.ManyToManyField(tardis.tardis_portal.api.InstrumentResource,
                               'instruments', null=True, full=True)

    class Meta(tardis.tardis_portal.api.MyTardisModelResource.Meta):
        resource_name = 'uploader'
        authentication = tardis.tardis_portal.api.default_authentication
        authorization = ACLAuthorization()
        queryset = Uploader.objects.all()
        filtering = {
            'mac_address': ('exact', ),
            'uuid': ('exact', ),
            'name': ('exact', ),
            'id': ('exact', ),
        }
        always_return_data = True

    def obj_create(self, bundle, **kwargs):
        bundle.data['created_time'] = datetime.now()
        bundle.data['updated_time'] = datetime.now()
        ip = get_ip(bundle.request)
        if ip is not None:
            bundle.data['wan_ip_address'] = ip
        bundle = super(UploaderAppResource, self).obj_create(bundle, **kwargs)
        return bundle

    def obj_update(self, bundle, **kwargs):
        # Workaround for
        # https://github.com/toastdriven/django-tastypie/issues/390 :
        if hasattr(bundle, "obj_update_done"):
            return
        bundle.data['updated_time'] = datetime.now()
        ip = get_ip(bundle.request)
        if ip is not None:
            bundle.data['wan_ip_address'] = ip
        bundle = super(UploaderAppResource, self).obj_update(bundle, **kwargs)
        bundle.obj_update_done = True
        return bundle


class UploaderRegistrationRequestAppResource(tardis.tardis_portal.api
                                             .MyTardisModelResource):
    uploader = fields.ForeignKey(
        'tardis.apps.mydata.api.UploaderAppResource', 'uploader')
    approved_storage_box = fields.ForeignKey(
        'tardis.tardis_portal.api.StorageBoxResource',
        'approved_storage_box', null=True, full=True)

    class Meta(tardis.tardis_portal.api.MyTardisModelResource.Meta):
        resource_name = 'uploaderregistrationrequest'
        authentication = tardis.tardis_portal.api.default_authentication
        authorization = ACLAuthorization()
        queryset = UploaderRegistrationRequest.objects.all()
        filtering = {
            'id': ('exact', ),
            'approved': ('exact', ),
            'requester_key_fingerprint': ('exact', ),
            'uploader': ALL_WITH_RELATIONS,
            'approved_storage_box': ALL_WITH_RELATIONS,
            'requester_key_fingerprint': ('exact', ),
        }
        always_return_data = True

    def obj_create(self, bundle, **kwargs):
        bundle = super(UploaderRegistrationRequestAppResource, self)\
            .obj_create(bundle, **kwargs)

        protocol = ""

        try:
            if hasattr(settings, "IS_SECURE") and settings.IS_SECURE:
                protocol = "s"

            current_site_complete = "http%s://%s" % \
                (protocol, Site.objects.get_current().domain)

            context = Context({
                'current_site': current_site_complete,
                'request_id': bundle.obj.id
            })

            subject = '[MyTardis] Uploader Registration Request Created'

            staff_users = User.objects.filter(is_staff=True)

            for staff in staff_users:
                if staff.email:
                    logger.info('email task dispatched to staff %s'
                                % staff.username)
                    email_user_task\
                        .delay(subject,
                               'uploader_registration_request_created',
                               context, staff)
        except:
            logger.error(traceback.format_exc())

        return bundle

    def hydrate(self, bundle):
        bundle = super(UploaderRegistrationRequestAppResource, self)\
            .hydrate(bundle)
        bundle.data['request_time'] = datetime.now()
        return bundle

    def save_related(self, bundle):
        if not hasattr(bundle.obj, 'approved_storage_box'):
            bundle.obj.approved_storage_box = None
        super(UploaderRegistrationRequestAppResource,
              self).save_related(bundle)


class ExperimentAppResource(tardis.tardis_portal.api.ExperimentResource):
    '''Extends MyTardis's API for Experiments
    to allow querying of metadata relevant to MyData
    '''

    class Meta(tardis.tardis_portal.api.ExperimentResource.Meta):
        # This will be mapped to mydata_experiment by MyTardis's urls.py:
        resource_name = 'experiment'

    def obj_get_list(self, bundle, **kwargs):
        '''
        Responds to uploader_uuid/user_folder_name query for MyData.
        Used by MyData to determine whether an appropriate default experiment
        exists to add a dataset to.  MyData generates the UUID the first time
        it runs on each upload PC. The UUID together with the user folder name
        can be used to uniquely identify one particular user who has saved data
        on an instrument PC running a MyData instance identified by the UUID.
        '''
        if hasattr(bundle.request, 'GET') and \
                'uploader_uuid' in bundle.request.GET and \
                'user_folder_name' in bundle.request.GET:

            uploader_uuid = bundle.request.GET['uploader_uuid']
            user_folder_name = bundle.request.GET['user_folder_name']

            mydata_default_exp_schema = Schema.objects.get(
                namespace='http://mytardis.org'
                '/schemas/mydata/defaultexperiment')

            exp_psets = ExperimentParameterSet.objects\
                .filter(schema=mydata_default_exp_schema)
            for exp_pset in exp_psets:
                exp_params = ExperimentParameter.objects\
                    .filter(parameterset=exp_pset)
                matched_uploader_uuid = False
                matched_user_folder_name = False
                for exp_param in exp_params:
                    if exp_param.name.name == "uploader_uuid" and \
                            exp_param.string_value == uploader_uuid:
                        matched_uploader_uuid = True
                    if exp_param.name.name == "user_folder_name" and \
                            exp_param.string_value == user_folder_name:
                        matched_user_folder_name = True
                if matched_uploader_uuid and matched_user_folder_name:
                    experiment_id = exp_pset.experiment.id
                    exp_list = Experiment.objects.filter(pk=experiment_id)
                    if exp_list[0] in Experiment.safe.all(bundle.request.user):
                        return exp_list

            return []

        '''
        Responds to uploader_uuid/user_folder_name/title query for MyData.
        '''
        if hasattr(bundle.request, 'GET') and \
                'uploader_uuid' in bundle.request.GET and \
                'owner' in bundle.request.GET and \
                'title' in bundle.request.GET:

            uploader_uuid = bundle.request.GET['uploader_uuid']
            user_folder_name = bundle.request.GET['user_folder_name']
            title = bundle.request.GET['title']

            mydata_default_exp_schema = Schema.objects.get(
                namespace='http://mytardis.org'
                '/schemas/mydata/defaultexperiment')

            exp_psets = ExperimentParameterSet.objects\
                .filter(schema=mydata_default_exp_schema)
            for exp_pset in exp_psets:
                exp_params = ExperimentParameter.objects\
                    .filter(parameterset=exp_pset)
                matched_uploader_uuid = False
                matched_user_folder_name = False
                for exp_param in exp_params:
                    if exp_param.name.name == "uploader_uuid" and \
                            exp_param.string_value == uploader_uuid:
                        matched_uploader_uuid = True
                    if exp_param.name.name == "user_folder_name" and \
                            exp_param.string_value == user_folder_name:
                        matched_user_folder_name = True
                if matched_uploader_uuid and matched_user_folder_name:
                    experiment_id = exp_pset.experiment.id
                    exp_list = Experiment.objects.filter(pk=experiment_id)
                    if exp_list[0] in Experiment.safe.all(bundle.request.user)\
                            .filter(title=title):
                        return exp_list

            return []

        return super(ExperimentAppResource, self).obj_get_list(bundle,
                                                               **kwargs)

    def save_m2m(self, bundle):
        '''
        MyData POSTs a UUID to identify the uploader (MyData instance)
        associated with this experiment.  Below, we find the Uploader
        model object which has that UUID.
        '''
        super(ExperimentAppResource, self).save_m2m(bundle)
        exp = bundle.obj
        mydata_exp_schema = \
            Schema.objects.filter(namespace='http://mytardis.org/schemas'
                                  '/mydata/defaultexperiment').first()
        if mydata_exp_schema is None:
            return
        mydata_exp_pset = \
            ExperimentParameterSet.objects.get(schema=mydata_exp_schema,
                                               experiment=exp)
        uploader_par_name = \
            ParameterName.objects.get(schema=mydata_exp_schema,
                                      name='uploader')
        uploader_param = \
            ExperimentParameter.objects.get(parameterset=mydata_exp_pset,
                                            name=uploader_par_name)
        uploader = Uploader.objects.get(uuid=uploader_param.string_value)
        uploader_param.link_id = uploader.id
        uploader_param.link_ct = uploader.get_ct()
        uploader_param.save()
