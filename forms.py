from django import forms
from django.shortcuts import render
from django.conf import settings
from django.contrib.auth.forms import AuthenticationForm, UserCreationForm
from django.contrib.auth.models import User
from django.core.exceptions import ValidationError
from django.utils.translation import ugettext_lazy as _
from django.http import HttpRequest, HttpResponseRedirect
from django.template import RequestContext
from app.models import Change, SUB_HDR_MSTR, SUB_HDR_REF, SUB_HDR_DETAIL, MDL_MSTR, PL_STRUCTURE, HEADER_CHOICES, SECTION_TYPE, FEAT_MSTR, DETAIL_TYPES, FEAT_PL_XREF, FEAT_DETAIL
from formtools.preview import FormPreview
from dal import autocomplete
from django.forms import ModelChoiceField
from django.contrib import messages
from django_select2.forms import Select2Widget, ModelSelect2Widget, Select2MultipleWidget

import pyodbc
import datetime

MAX = 100
server_name = "C001632619\MSSQLDEV"
cnxn = pyodbc.connect("DSN=test;Trusted_Connection=yes;")
cursor = cnxn.cursor()

##Good link for preview forms: https://django-formtools.readthedocs.io/en/latest/_modules/formtools/preview.html

#Below are the choices that populate the drop-down lists
SELECTION_CHOICES = (
    (1, "View Feature Code"),
    (2, "Add Feature Code Description"),
    (3, "Delete Feature Code Description"),
    (4, "Edit Feature Code Description")
)

def order(model):
    sequence = 1


def get_time():
    time = "%i/%i/%i %i:%i" %(datetime.datetime.now().year, 
                              datetime.datetime.now().month,
                              datetime.datetime.now().day,
                              datetime.datetime.now().hour,
                              datetime.datetime.now().minute)
    return time

# Authentication form provided as default by Django, downloaded with Bootstrap
# This form is user to authenticate users logging in
class BootstrapAuthenticationForm(AuthenticationForm):
    username = forms.CharField(max_length=254,
                               widget=forms.TextInput({
                                   'class': 'form-control',
                                   'placeholder': 'User name'}))
    password = forms.CharField(label=_("Password"),
                               widget=forms.PasswordInput({
                                   'class': 'form-control',
                                   'placeholder':'Password'}))

# This form is used to sign up new users
class SignupForm(UserCreationForm):
    username = forms.CharField(label='Enter Username', min_length=4, max_length=150, widget=forms.TextInput)
    email = forms.EmailField(label='Enter Email', widget=forms.EmailInput, initial = '@cat.com')
    password1 = forms.CharField(label='Enter Password', widget=forms.PasswordInput)
    password2 = forms.CharField(label='Confirm Password', widget=forms.PasswordInput)
    elevated_access = forms.BooleanField(label='Requesting Elevated Access?', widget=forms.CheckboxInput, initial = False, required = False,
                                         help_text = 'Users with elevated access are able to publish changes directly to the database, without administrator approval.')
 
    def clean_username(self):
        username = self.cleaned_data['username'].lower()
        r = User.objects.filter(username=username)
        if r.count():
            raise  ValidationError("Username already exists")
        return username
 
    def clean_email(self):
        email = self.cleaned_data['email'].lower()
        r = User.objects.filter(email=email)
        if r.count():
            raise  ValidationError("Email already exists")
        return email
 
    def clean_password2(self):
        password1 = self.cleaned_data.get('password1')
        password2 = self.cleaned_data.get('password2')
 
        if password1 and password2 and password1 != password2:
            raise ValidationError("Password don't match")
 
        return password2

    def clean_elevated_access(self):
        elevated_request = self.cleaned_data.get('elevated_access')
        return elevated_request
 
    def save(self, commit=True):
        user = User.objects.create_user(
            self.cleaned_data['username'],
            self.cleaned_data['email'],
            self.cleaned_data['password1']
        )
        return user

# This is the form featured on the Main page. User selects, the Price List, feature code, and action
class SelectAction(forms.Form):
    engine_model = forms.ModelChoiceField(label = "Engine Model",queryset = MDL_MSTR.objects.all(), empty_label="------", widget = Select2Widget(),
                                          help_text='Only models available in the database can be\nedited with this tool.')
    feature_code = forms.CharField(label='Feature Code',
                                   initial = 'fltoil3',
                                   max_length=MAX,
                                   widget=forms.TextInput({
                                       'class': 'form-control',
                                       'placeholder': 'Feature ID'}),
                                   min_length = None,
                                   help_text = 'Enter a valid feature code that exists under\nthe price list model that you have selected.\nThe feature code does not need to be capitalized.')
    action = forms.ChoiceField(label = "Action",choices = SELECTION_CHOICES, widget = forms.RadioSelect())    

    def clean_engine_model(self):
        model_selection = self.cleaned_data['engine_model']
        return model_selection

    def clean_action(self):
        action_selection = self.cleaned_data['action']
        if action_selection == 0:
            raise forms.ValidationError("Select an action.")
        return action_selection

    def clean_feature_code(self):
        feature_code_input = self.cleaned_data['feature_code'].upper()
        model_selection = self.cleaned_data['engine_model']
        pl_id = model_selection.pl_id
        feature_id = FEAT_MSTR.objects.filter(FEAT_NM = feature_code_input).values_list('FEAT_ID',flat = True)
        num_results = FEAT_PL_XREF.objects.filter(FEAT_ID = feature_id).filter(pl_id = pl_id).count()
        if num_results == 0:
            raise forms.ValidationError("The feature code you entered does not exist for this product.")
        return feature_code_input

# This form obtains user input for the desired removal of a feature code detail.
# NOTE: The __init__() function accepts request as a parameter to generate the form.
class DeleteFeatureCode(forms.Form):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(DeleteFeatureCode, self).__init__(*args, **kwargs)
        self.fields['deleted_text'] = forms.ModelChoiceField(FEAT_DETAIL.objects.filter(pl_id = self.request.session['pl_id']).filter(FEAT_ID = self.request.session['feature_id']),
                                                             widget = forms.RadioSelect,
                                                             empty_label = None)
 
        
    def clean_deleted_text(self):
        deleted_text_selection = self.cleaned_data['deleted_text']
        return deleted_text_selection

# This form displays what the user's input would result in, and publishes it if the user approves.
class DeleteFeatureCodePreview(FormPreview):
    preview_template = 'app/preview_delete.html'

    ## The following function was obtained from the website listed at the top of this page. Any edits made to it have been included in the comments.
    def preview_post(self, request):
        
        f = self.form(request.POST, request = request, auto_id=self.get_auto_id()) ## changed from default preview_post to include request
        context = self.get_context(request, f)
        print("preview post")
        if f.is_valid():
            self.process_preview(request, f, context)
            context['hash_field'] = self.unused_name('hash')
            context['hash_value'] = self.security_hash(request, f)
            return render(request, self.preview_template, context)
        else:
            print("preview post")
            return render(request, self.form_template, context)
    
    ## The following function was obtained from the website listed at the top of this page. Any edits made to it have been included in the comments.
    def post_post(self, request):
        form = self.form(request.POST, request = request, auto_id=self.get_auto_id())
        if form.is_valid():
            if not self._check_security_hash(
                    request.POST.get(self.unused_name('hash'), ''),
                    request, form):
                return self.failed_hash(request)  # Security hash failed.
            return self.done(request, form.cleaned_data)
        else:
            return render(request, self.form_template, self.get_context(request, form))

    def done(self, request, cleaned_data):
        deleted_text =  cleaned_data['deleted_text'].DTL_TEXT
        removal = FEAT_DETAIL.objects.filter(DTL_TEXT = deleted_text)
        if request.user.is_superuser:
            delete = """DELETE FROM Test.CPL_TEST.FEAT_DETAIL 
                        WHERE pl_id = %i AND FEAT_ID = %i AND DTL_SEQ = %i""" % (int(request.session['pl_id']),
                                                          int(request.session['feature_id']),
                                                          int(removal.values_list('DTL_SEQ',flat = True)[0]))
            cursor.execute(delete)
            cnxn.commit()
            change = Change(
                    user_id = request.user.username,
                    pl_id = request.session['pl_id'],
                    FEAT_ID = request.session['feature_id'],
                    FEAT_NM = request.session['feature_name'],
                    DTL_SEQ = removal.values_list('DTL_SEQ',flat = True)[0],
                    DTL_TYPE_original = removal.values_list('DTL_TYPE', flat = True)[0],
                    #DTL_TYPE_updated = null,
                    DTL_TEXT_original = deleted_text,
                    #DTL_TEXT_updated = Null,
                    status = 'p',
                    edit_type = 'r'
                    )
            removal.delete()
        else:
            change = Change(
                    user_id = request.user.username,
                    pl_id = request.session['pl_id'],
                    FEAT_ID = request.session['feature_id'],
                    FEAT_NM = request.session['feature_name'],
                    DTL_SEQ = removal.values_list('DTL_SEQ',flat = True)[0],
                    DTL_TYPE_original = removal.values_list('DTL_TYPE', flat = True)[0],
                    #DTL_TYPE_updated = null,
                    DTL_TEXT_original = deleted_text,
                    #DTL_TEXT_updated = null,
                    status = 'd',
                    edit_type = 'r'
                    )
            msg = "User %s has requested a change to feature code %s" %(request.user.username, request.session['feature_name'])
            messages.warning(request, msg, extra_tags = get_time())
        change.save()
        return render(request, 'app/success.html', {
                    'info': 'Success!'
                    })

    def process_preview(self, request, form, context):
        context['detail_text'] = form.cleaned_data['deleted_text'].DTL_TEXT
        context['feature_name'] = request.session['feature_name']
        context['feature_desc'] = request.session['feature_desc']
        context['use_code'] = request.session['use_code']
        context['detail_key'] = list(DETAIL_TYPES.objects.all())
        context['form'] = form
        context['details'] = list(FEAT_DETAIL.objects.filter(FEAT_ID = request.session['feature_id']).filter(pl_id = request.session['pl_id']).order_by('DTL_SEQ'))

# This form accepts user input for editing an existing feature code.
# NOTE: The __init__() function accepts request as a parameter to generate the form.
class EditFeatureCode(forms.Form):
    def __init__(self, *args, **kwargs):
        self.request = kwargs.pop('request', None)
        super(EditFeatureCode, self).__init__(*args, **kwargs)
        self.fields['edited_text'] = forms.ModelChoiceField(FEAT_DETAIL.objects.filter(pl_id = self.request.session['pl_id']).filter(FEAT_ID = self.request.session['feature_id']),
                                                             widget = forms.RadioSelect,
                                                             empty_label = None)
        self.fields['detail_type'] =  forms.ModelChoiceField(queryset=DETAIL_TYPES.objects.all().order_by('DTL_DESC'),
                                                             help_text = '*GENERAL notes will be displayed on price list without type indicators')
        self.fields['new_text'] = forms.CharField(label='Desired Text',
                                   widget=forms.Textarea({
                                       'class': 'form-control',
                                       'placeholder': 'Enter the replacement text.'}),
                                   min_length = None)

    def cleaned_edited_text(self):
        edited_text_selection = self.cleaned_data['edited_text']
        return edited_text_selection

    def cleaned_detail_type(self):
        detail_type_selection = self.cleaned_data['detail_type']
        return detail_type_selection

    def cleaned_new_text(self):
        edited_new_selection = self.cleaned_data['new_text']
        return new_text_selection

# This form displays what the user's input would result in, and publishes it if the user approves.
class EditFeatureCodePreview(FormPreview):
    preview_template = 'app/preview_edit.html'

    ## The following function was obtained from the website listed at the top of this page. Any edits made to it have been included in the comments.
    def preview_post(self, request):
        f = self.form(request.POST, request = request, auto_id=self.get_auto_id()) ## changed from default preview_post to include request
        context = self.get_context(request, f)
        if f.is_valid():
            self.process_preview(request, f, context) 
            context['hash_field'] = self.unused_name('hash')
            context['hash_value'] = self.security_hash(request, f)
            return render(request, self.preview_template, context)
        else:
            return render(request, self.form_template, context)
    
    ## The following function was obtained from the website listed at the top of this page. Any edits made to it have been included in the comments.
    def post_post(self, request):
        form = self.form(request.POST, request = request, auto_id=self.get_auto_id()) ## changed from default preview_post to include request
        if form.is_valid():
            if not self._check_security_hash(
                    request.POST.get(self.unused_name('hash'), ''),
                    request, form):
                return self.failed_hash(request)  # Security hash failed.
            return self.done(request, form.cleaned_data)
        else:
            return render(request, self.form_template, self.get_context(request, form))

    def done(self, request, cleaned_data):
        feature_model = cleaned_data['edited_text']
        print(feature_model.DTL_SEQ)
        if request.user.is_superuser:
            edit = """UPDATE Test.CPL_TEST.FEAT_DETAIL 
            SET DTL_TYP = '%s', DTL_TEXT = '%s'
            WHERE pl_id = %i AND FEAT_ID = %i AND DTL_SEQ = %i""" % (cleaned_data['detail_type'].DTL_TYPE,
                                                                     cleaned_data['new_text'],
                                                                     int(request.session['pl_id']),
                                                                     int(request.session['feature_id']),
                                                                     feature_model.DTL_SEQ)
            cursor.execute(edit)
            cnxn.commit()
            change = Change(
                    user_id = request.user.username,
                    pl_id = request.session['pl_id'],
                    FEAT_ID = request.session['feature_id'],
                    FEAT_NM = request.session['feature_name'],
                    DTL_SEQ = int(feature_model.DTL_SEQ),
                    DTL_TYPE_original = feature_model.DTL_TYPE,
                    DTL_TEXT_original = feature_model.DTL_TEXT,
                    DTL_TYPE_updated = cleaned_data.get('detail_type').DTL_TYPE,
                    DTL_TEXT_updated = cleaned_data['new_text'],
                    status = 'p',
                    edit_type = 'e'
                    )
            change.save()
            feature_model.DTL_TEXT = cleaned_data['new_text']
            feature_model.DTL_TYPE = cleaned_data['detail_type'].DTL_TYPE
            feature_model.save(update_fields=['DTL_TEXT','DTL_TYPE'])
        else:
            change = Change(
                    user_id = request.user.username,
                    pl_id = request.session['pl_id'],
                    FEAT_ID = request.session['feature_id'],
                    FEAT_NM = request.session['feature_name'],
                    DTL_SEQ = int(feature_model.DTL_SEQ),
                    DTL_TYPE_original = feature_model.DTL_TYPE,
                    DTL_TEXT_original = feature_model.DTL_TEXT,
                    DTL_TYPE_updated = cleaned_data.get('detail_type').DTL_TYPE,
                    DTL_TEXT_updated = cleaned_data['new_text'],
                    status = 'd',
                    edit_type = 'e'
                    )
            change.save()
            msg = "User %s has requested a change to feature code %s" %(request.user.username, request.session['feature_name'])
            messages.warning(request, msg, extra_tags = get_time())
        return render(request, 'app/success.html', {
                    'info': 'Success!'
                    })

    def process_preview(self, request, form, context):
        context['detail_text'] = form.cleaned_data['edited_text'].DTL_TEXT
        context['detail_type'] = form.cleaned_data['detail_type'].DTL_DESC
        context['new_text'] = form.cleaned_data['new_text']
        context['feature_name'] = request.session['feature_name']
        context['feature_desc'] = request.session['feature_desc']
        context['use_code'] = request.session['use_code']
        context['detail_key'] = list(DETAIL_TYPES.objects.all())
        context['form'] = form
        context['details'] = list(FEAT_DETAIL.objects.filter(FEAT_ID = request.session['feature_id']).filter(pl_id = request.session['pl_id']).order_by('DTL_SEQ'))

# This form accepts user input for adding a new detail to an existing feature code.
class AddFeatureCode(forms.Form):
    detail_type = forms.ModelChoiceField(queryset=DETAIL_TYPES.objects.all().order_by('DTL_DESC'),
                                         help_text = '*GENERAL notes will be displayed on price list without type indicators')
    detail_text = forms.CharField(label='Detail Text',
                                   widget=forms.Textarea({
                                       'class': 'form-control',
                                       'placeholder': 'Indicate the text you would like to add.'}),
                                   min_length = None)

    def clean_detail_type(self):
        detail_type_selection = self.cleaned_data['detail_type']
        return detail_type_selection

    def clean_detail_text(self):
        detail_text_input = self.cleaned_data['detail_text']
        return detail_text_input

# This form displays what the user's input would result in, and publishes it if the user approves.
class AddFeatureCodePreview(FormPreview):
    preview_template = 'app/preview_add.html'

    def done(self, request, cleaned_data):
        num_objects = FEAT_DETAIL.objects.filter(FEAT_ID = request.session['feature_id']).filter(pl_id = request.session['pl_id']).order_by('-DTL_SEQ').values_list('DTL_SEQ', flat = True)[0] + 1
        detail_type = cleaned_data.get('detail_type')
        print(num_objects)
        if request.user.is_superuser:
            insert = """INSERT INTO Test.CPL_TEST.FEAT_DETAIL (pl_id, FEAT_ID, DTL_SEQ, DTL_TYP, DTL_TEXT) 
                    VALUES (%i, %i, %i, '%s', '%s')""" % (int(request.session['pl_id']),
                                                          int(request.session['feature_id']),
                                                          num_objects, 
                                                          detail_type.DTL_TYPE, 
                                                          cleaned_data['detail_text'])
            cursor.execute(insert)
            cnxn.commit()
            added_text = FEAT_DETAIL(
                pl_id = request.session['pl_id'],
                FEAT_ID = request.session['feature_id'],
                DTL_SEQ = num_objects,
                DTL_TYPE = detail_type.DTL_TYPE,
                DTL_TEXT = cleaned_data['detail_text']
                )
            added_text.save()
            change = Change(
                user_id = request.user.username,
                pl_id = request.session['pl_id'],
                FEAT_ID = request.session['feature_id'],
                FEAT_NM = request.session['feature_name'],
                DTL_SEQ = num_objects,
                DTL_TYPE_updated = detail_type.DTL_TYPE,
                #DTL_TYPE_original = null,
                DTL_TEXT_updated = cleaned_data['detail_text'],
                #DTL_TEXT_original = null,
                status = 'p',
                edit_type = 'a'
                )
        else:
            change = Change(
                user_id = request.user.username,
                pl_id = request.session['pl_id'],
                FEAT_ID = request.session['feature_id'],
                FEAT_NM = request.session['feature_name'],
                DTL_SEQ = num_objects,
                DTL_TYPE_updated = detail_type.DTL_TYPE,
                #DTL_TYPE_originial = null,
                DTL_TEXT_updated = cleaned_data['detail_text'],
                #DTL_TYPE_updated = null,
                status = 'd',
                edit_type = 'a'
                )
            msg = "User %s has requested a change to feature code %s" %(request.user.username, request.session['feature_name'])
            messages.warning(request, msg, extra_tags = get_time())
        change.save()
        return render(request, 'app/success.html', {
                    'info': 'Success!'
                    })

    def process_preview(self, request, form, context):
        detail = form.cleaned_data['detail_type']
        context['detail_type'] = detail.DTL_DESC
        context['detail_text'] = form.cleaned_data.get('detail_text')
        context['feature_name'] = request.session['feature_name']
        context['feature_desc'] = request.session['feature_desc']
        context['use_code'] = request.session['use_code']
        context['detail_key'] = list(DETAIL_TYPES.objects.all())
        context['form'] = form
        context['details'] = list(FEAT_DETAIL.objects.filter(FEAT_ID = request.session['feature_id']).filter(pl_id = request.session['pl_id']).order_by('DTL_SEQ'))