from django import forms
from decimal import Decimal
from .models import FeeVoucher, FeePayment, FeeVoucherTypeChoices, Challan, Payment
from students.models import StudentProfile


class ChallanForm(forms.ModelForm):
    class Meta:
        model = Challan
        fields = ['student', 'academic_year', 'month', 'year', 'total', 'due_date', 'remarks']
        widgets = {
            'student': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'academic_year': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'month': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'placeholder': 'e.g. August 2026'}),
            'year': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600'}),
            'total': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'step': '0.01'}),
            'due_date': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'type': 'date'}),
            'remarks': forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600', 'rows': 2}),
        }

    def __init__(self, *args, school=None, **kwargs):
        super().__init__(*args, **kwargs)
        if school:
            self.fields['student'].queryset = StudentProfile.objects.filter(class_level__school=school)


class VirtualPaymentForm(forms.Form):
    amount = forms.DecimalField(max_digits=10, decimal_places=2, min_value=Decimal('0.01'), widget=forms.NumberInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'step': '0.01'
    }))
    notes = forms.CharField(required=False, widget=forms.TextInput(attrs={
        'class': 'w-full px-3 py-2 bg-white border border-slate-300 rounded-xl text-slate-900 focus:ring-2 focus:ring-blue-600',
        'placeholder': 'Optional payment note (e.g. Virtual simulated check)'
    }))



class FeeVoucherForm(forms.ModelForm):
    class Meta:
        model = FeeVoucher
        fields = [
            'student', 'academic_session', 'voucher_type', 'billing_month',
            'issue_date', 'due_date',
            'monthly_fee', 'total_fee', 'submitted_fee', 'remaining_fee', 'allow_advance_payment',
            'tuition_fee', 'admission_fee', 'exam_fee', 'transport_fee',
            'hostel_fee', 'previous_balance', 'late_fine', 'other_charges',
            'discount_amount', 'discount_remarks', 'remarks'
        ]
        widgets = {
            'student': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'id': 'id_student'}),
            'academic_session': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]'}),
            'voucher_type': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]'}),
            'billing_month': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'placeholder': 'e.g. August 2026'}),
            'issue_date': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'type': 'date'}),
            'due_date': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'type': 'date'}),

            # Period Totals & Monthly Fee
            'monthly_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_monthly_fee'}),
            'total_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_total_fee'}),
            'submitted_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_submitted_fee'}),
            'remaining_fee': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 bg-slate-900 border border-slate-700 rounded-xl text-[#9ece38] font-mono font-bold cursor-not-allowed', 'step': '0.01', 'id': 'id_remaining_fee', 'readonly': 'readonly'}),
            'allow_advance_payment': forms.CheckboxInput(attrs={'class': 'rounded bg-slate-950 border-slate-700 text-[#ff8000] focus:ring-0', 'id': 'id_allow_advance_payment'}),

            # Particular Components
            'tuition_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_tuition_fee'}),
            'admission_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_admission_fee'}),
            'exam_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_exam_fee'}),
            'transport_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_transport_fee'}),
            'hostel_fee': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_hostel_fee'}),
            'previous_balance': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_previous_balance'}),
            'late_fine': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_late_fine'}),
            'other_charges': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_other_charges'}),

            'discount_amount': forms.NumberInput(attrs={'class': 'calc-field w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'step': '0.01', 'min': '0', 'id': 'id_discount_amount'}),
            'discount_remarks': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'placeholder': 'e.g. 20% Merit Concession'}),
            'remarks': forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#ff8000]', 'rows': 2}),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['remaining_fee'].required = False

    def clean(self):
        cleaned_data = super().clean()
        total_fee = cleaned_data.get('total_fee') or Decimal('0.00')
        submitted_fee = cleaned_data.get('submitted_fee') or Decimal('0.00')
        allow_advance = cleaned_data.get('allow_advance_payment') or False

        # Validate non-negative numbers
        num_fields = ['monthly_fee', 'total_fee', 'submitted_fee', 'tuition_fee', 'admission_fee',
                      'exam_fee', 'transport_fee', 'hostel_fee', 'previous_balance', 'late_fine',
                      'other_charges', 'discount_amount']
        for field in num_fields:
            val = cleaned_data.get(field)
            if val is not None and val < Decimal('0.00'):
                self.add_error(field, "Negative amounts are not allowed.")

        # Validate Submitted Fee <= Total Fee
        if not allow_advance and submitted_fee > total_fee and total_fee > Decimal('0.00'):
            self.add_error('submitted_fee', "Submitted Fee cannot be greater than Total Fee unless Advance Payment is enabled.")

        return cleaned_data


class FeePaymentForm(forms.ModelForm):
    class Meta:
        model = FeePayment
        fields = ['amount_paid', 'payment_date', 'payment_method', 'transaction_reference', 'notes']
        widgets = {
            'amount_paid': forms.NumberInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#009688]', 'step': '0.01', 'min': '0', 'id': 'id_amount_paid'}),
            'payment_date': forms.DateInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#009688]', 'type': 'date'}),
            'payment_method': forms.Select(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#009688]'}),
            'transaction_reference': forms.TextInput(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#009688]', 'placeholder': 'Cheque #, Bank Ref, or Online Txn ID'}),
            'notes': forms.Textarea(attrs={'class': 'w-full px-3 py-2 bg-slate-950/80 border border-slate-700 rounded-xl text-white focus:ring-2 focus:ring-[#009688]', 'rows': 2}),
        }
