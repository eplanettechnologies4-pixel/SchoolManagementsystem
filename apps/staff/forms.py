import os
import datetime
from django import forms
from django.utils.translation import gettext_lazy as _
from django.core.exceptions import ValidationError
from staff.models import (
    Staff, StaffDocument, StaffAttendance, LeaveRequest,
    LeaveType, ShiftTiming, EmploymentTypeChoices, StaffStatusChoices,
    SalarySlip, SalaryPaymentMethodChoices, LateDeductionPolicyChoices
)
from students.services.student_service import (
    validate_pakistan_cnic, validate_pakistan_phone, standardize_phone
)


class StaffForm(forms.ModelForm):
    first_name = forms.CharField(max_length=100, label=_("First Name"))
    last_name = forms.CharField(max_length=100, label=_("Last Name"))
    email = forms.EmailField(label=_("Official Email"))

    class Meta:
        model = Staff
        fields = [
            'designation', 'department', 'qualification', 'joining_date',
            'phone', 'cnic', 'employment_type', 'status', 'shift',
            'basic_salary', 'allowances', 'late_deduction_policy',
            'bank_name', 'bank_account_number',
            'emergency_contact', 'address', 'photo'
        ]
        widgets = {
            'designation': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'department': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'qualification': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'joining_date': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'type': 'date'}),
            'phone': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'placeholder': '+923001234567'}),
            'cnic': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'placeholder': '35202-1234567-1'}),
            'employment_type': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'status': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'shift': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'basic_salary': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'step': '0.01'}),
            'allowances': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'step': '0.01'}),
            'late_deduction_policy': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'bank_name': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'placeholder': 'e.g. HBL / Meezan Bank'}),
            'bank_account_number': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'placeholder': 'IBAN or Account Number'}),
            'emergency_contact': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'address': forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'rows': 2}),
            'photo': forms.FileInput(attrs={'class': 'w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 border border-slate-300 rounded-xl bg-white'}),
        }

    def clean_cnic(self):
        val = self.cleaned_data.get('cnic')
        if val:
            validate_pakistan_cnic(val)
        return val

    def clean_phone(self):
        val = self.cleaned_data.get('phone')
        if val:
            validate_pakistan_phone(val)
            return standardize_phone(val)
        return val


class LeaveRequestForm(forms.ModelForm):
    class Meta:
        model = LeaveRequest
        fields = ['leave_type', 'from_date', 'to_date', 'reason']
        widgets = {
            'leave_type': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'from_date': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'type': 'date'}),
            'to_date': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'type': 'date'}),
            'reason': forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'rows': 3, 'placeholder': _("Reason for leave request...")}),
        }

    def clean(self):
        cleaned_data = super().clean()
        from_date = cleaned_data.get('from_date')
        to_date = cleaned_data.get('to_date')
        if from_date and to_date and to_date < from_date:
            raise ValidationError(_("End date cannot be earlier than start date."))
        return cleaned_data


class LeaveReviewForm(forms.Form):
    status = forms.ChoiceField(
        choices=[('APPROVED', _('Approve')), ('REJECTED', _('Reject'))],
        widget=forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'})
    )
    review_comments = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'rows': 2, 'placeholder': _("Optional feedback or remarks...")})
    )


class StaffCheckInForm(forms.Form):
    latitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False)
    longitude = forms.DecimalField(max_digits=9, decimal_places=6, required=False)


class StaffDocumentForm(forms.ModelForm):
    class Meta:
        model = StaffDocument
        fields = ['title', 'document_type', 'file']
        widgets = {
            'title': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'document_type': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'file': forms.FileInput(attrs={'class': 'w-full text-xs text-slate-600 file:mr-4 file:py-2 file:px-4 file:rounded-xl file:border-0 file:bg-blue-50 file:text-blue-700 hover:file:bg-blue-100 border border-slate-300 rounded-xl bg-white'}),
        }


class PayrollGenerateForm(forms.Form):
    month = forms.ChoiceField(
        choices=[(i, datetime.date(2000, i, 1).strftime('%B')) for i in range(1, 13)],
        widget=forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'})
    )
    year = forms.IntegerField(
        initial=datetime.date.today().year,
        widget=forms.NumberInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'})
    )


class SalarySlipPaymentForm(forms.Form):
    payment_method = forms.ChoiceField(
        choices=SalaryPaymentMethodChoices.choices,
        widget=forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'})
    )
    transaction_reference = forms.CharField(
        required=False,
        widget=forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'placeholder': 'Bank Ref / Cheque No / Cash Receipt'})
    )
    remarks = forms.CharField(
        required=False,
        widget=forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'rows': 2, 'placeholder': 'Optional disbursement remarks...'})
    )


