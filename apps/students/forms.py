import os
import re
import datetime
from decimal import Decimal
from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError

from students.models import (
    StudentProfile, GuardianProfile, StudentStatusChoices,
    GenderChoices, StudentDocumentType
)
from academics.models import ClassLevel, Section
from students.services.student_service import (
    validate_pakistan_cnic, validate_pakistan_phone, standardize_phone,
    process_and_compress_photo
)


class StudentAdmissionStep1Form(forms.Form):
    first_name = forms.CharField(max_length=100, label=_("Student First Name"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'placeholder': _("e.g. Muhammad")
    }))
    last_name = forms.CharField(max_length=100, label=_("Student Last Name"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'placeholder': _("e.g. Ali")
    }))
    gender = forms.ChoiceField(choices=GenderChoices.choices, label=_("Gender"), widget=forms.Select(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    dob = forms.DateField(label=_("Date of Birth"), widget=forms.DateInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'type': 'date'
    }))
    bform_number = forms.CharField(max_length=30, label=_("B-Form / Child CNIC"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'placeholder': '35202-1234567-1'
    }))
    religion = forms.CharField(max_length=50, initial="Islam", label=_("Religion"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    blood_group = forms.ChoiceField(
        choices=[('', '-- Select Blood Group --'), ('A+', 'A+'), ('A-', 'A-'), ('B+', 'B+'), ('B-', 'B-'), ('O+', 'O+'), ('O-', 'O-'), ('AB+', 'AB+'), ('AB-', 'AB-')],
        required=False,
        label=_("Blood Group"),
        widget=forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'})
    )
    nationality = forms.CharField(max_length=50, initial="Pakistani", label=_("Nationality"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    photo = forms.ImageField(required=False, label=_("Passport Photo (Max 2MB)"), widget=forms.FileInput(attrs={
        'class': 'w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 border border-slate-300 rounded-xl bg-white',
        'accept': 'image/*'
    }))

    def clean_bform_number(self):
        val = self.cleaned_data['bform_number']
        validate_pakistan_cnic(val)
        return val


class StudentAdmissionStep2Form(forms.Form):
    father_name = forms.CharField(max_length=100, label=_("Father's Full Name"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    mother_name = forms.CharField(max_length=100, required=False, label=_("Mother's Full Name"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    guardian_first_name = forms.CharField(max_length=100, label=_("Primary Guardian First Name"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    guardian_last_name = forms.CharField(max_length=100, label=_("Primary Guardian Last Name"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    relation = forms.CharField(max_length=50, initial="Father", label=_("Relationship to Student"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    guardian_cnic = forms.CharField(max_length=30, label=_("Guardian CNIC"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'placeholder': '35202-1234567-1'
    }))
    phone = forms.CharField(max_length=30, label=_("Primary Phone / Mobile (+92)"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'placeholder': '+923001234567'
    }))
    whatsapp_number = forms.CharField(max_length=30, required=False, label=_("WhatsApp Notification Number"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'placeholder': '+923001234567'
    }))
    occupation = forms.CharField(max_length=100, required=False, label=_("Guardian Occupation"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    address = forms.CharField(widget=forms.Textarea(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'rows': 2
    }), label=_("Residential Address"))
    emergency_contact = forms.CharField(max_length=30, label=_("Emergency Contact Number"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))

    def clean_guardian_cnic(self):
        val = self.cleaned_data['guardian_cnic']
        validate_pakistan_cnic(val)
        return val

    def clean_phone(self):
        val = self.cleaned_data['phone']
        validate_pakistan_phone(val)
        return standardize_phone(val)


class StudentAdmissionStep3Form(forms.Form):
    class_level = forms.ModelChoiceField(
        queryset=ClassLevel.objects.filter(is_active=True, is_deleted=False).order_by('numeric_order'),
        label=_("Admission Class Level"),
        widget=forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'id': 'id_class_level'})
    )
    section = forms.ModelChoiceField(
        queryset=Section.objects.filter(is_active=True, is_deleted=False),
        label=_("Allocated Section (With Available Capacity)"),
        widget=forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'id': 'id_section'})
    )
    admission_date = forms.DateField(initial=datetime.date.today, label=_("Admission Date"), widget=forms.DateInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'type': 'date'
    }))
    previous_school = forms.CharField(max_length=200, required=False, label=_("Previous School Attended"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    previous_class = forms.CharField(max_length=100, required=False, label=_("Last Class Passed"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))
    last_result = forms.CharField(max_length=100, required=False, label=_("Previous Exam Grade / Marks"), widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'
    }))

    def clean(self):
        cleaned_data = super().clean()
        section = cleaned_data.get('section')
        if section:
            if section.is_full:
                raise ValidationError(f"Selected section '{section.name}' is already at full capacity ({section.capacity}/{section.capacity} filled). Please choose another section.")
        return cleaned_data


class StudentAdmissionStep4Form(forms.Form):
    bform_doc = forms.FileField(required=False, label=_("B-Form / Birth Certificate Copy (PDF/JPG/PNG, Max 5MB)"), widget=forms.FileInput(attrs={
        'class': 'w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 border border-slate-300 rounded-xl bg-white'
    }))
    cnic_doc = forms.FileField(required=False, label=_("Father / Guardian CNIC Copy (PDF/JPG/PNG, Max 5MB)"), widget=forms.FileInput(attrs={
        'class': 'w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 border border-slate-300 rounded-xl bg-white'
    }))
    marksheet_doc = forms.FileField(required=False, label=_("Previous Marksheet / Result Card (PDF/JPG/PNG, Max 5MB)"), widget=forms.FileInput(attrs={
        'class': 'w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 border border-slate-300 rounded-xl bg-white'
    }))
    transfer_doc = forms.FileField(required=False, label=_("School Leaving / Transfer Certificate (PDF/JPG/PNG, Max 5MB)"), widget=forms.FileInput(attrs={
        'class': 'w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 border border-slate-300 rounded-xl bg-white'
    }))

    ALLOWED_EXTENSIONS = ('.pdf', '.jpg', '.jpeg', '.png', '.webp')
    MAX_SIZE = 5 * 1024 * 1024

    def _validate_file(self, field_name):
        f = self.cleaned_data.get(field_name)
        if f:
            ext = os.path.splitext(f.name)[1].lower()
            if ext not in self.ALLOWED_EXTENSIONS:
                raise ValidationError(f"Unsupported file format '{ext}'. Allowed: PDF, JPG, PNG, WEBP.")
            if f.size > self.MAX_SIZE:
                raise ValidationError("Document file size exceeds 5MB limit.")
        return f

    def clean_bform_doc(self):
        return self._validate_file('bform_doc')

    def clean_cnic_doc(self):
        return self._validate_file('cnic_doc')

    def clean_marksheet_doc(self):
        return self._validate_file('marksheet_doc')

    def clean_transfer_doc(self):
        return self._validate_file('transfer_doc')


class StudentEditForm(forms.ModelForm):
    first_name = forms.CharField(max_length=100, label=_("First Name"))
    last_name = forms.CharField(max_length=100, label=_("Last Name"))
    phone_number = forms.CharField(max_length=30, required=False, label=_("Personal Phone"))

    class Meta:
        model = StudentProfile
        fields = [
            'class_level', 'section', 'roll_number', 'dob', 'gender',
            'bform_number', 'religion', 'blood_group', 'nationality',
            'emergency_contact', 'address', 'status',
            'previous_school', 'previous_class', 'last_result'
        ]
        widgets = {
            'class_level': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'section': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'roll_number': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'dob': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'type': 'date'}),
            'gender': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'bform_number': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'religion': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'blood_group': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'nationality': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'emergency_contact': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'address': forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'rows': 2}),
            'status': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'previous_school': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'previous_class': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'last_result': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        if self.instance and self.instance.user:
            self.fields['first_name'].initial = self.instance.user.first_name
            self.fields['last_name'].initial = self.instance.user.last_name
            self.fields['phone_number'].initial = self.instance.user.phone_number
