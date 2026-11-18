from django import forms
from django.core.exceptions import ValidationError
from .models import ClassLevel, Section, Subject, CurriculumPDF
from accounts.models import User, RoleChoices

class CurriculumPDFForm(forms.ModelForm):
    class Meta:
        model = CurriculumPDF
        fields = ['title', 'pdf_file', 'version_notes']
        widgets = {
            'title': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-white text-xs focus:ring-2 focus:ring-[#009688]',
                'placeholder': 'e.g. Official Curriculum & Subject List 2026-2027'
            }),
            'version_notes': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-white text-xs focus:ring-2 focus:ring-[#009688]',
                'placeholder': 'e.g. Updated Math and Science syllabus for Class 9 & 10'
            }),
            'pdf_file': forms.FileInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-slate-300 text-xs focus:ring-2 focus:ring-[#009688]',
                'accept': 'application/pdf'
            }),
        }

    def clean_pdf_file(self):
        pdf_file = self.cleaned_data.get('pdf_file')
        if pdf_file:
            if not pdf_file.name.lower().endswith('.pdf'):
                raise ValidationError("Only PDF files (.pdf) are allowed.")
            # Limit file size to 20MB
            if pdf_file.size > 20 * 1024 * 1024:
                raise ValidationError("File size must not exceed 20MB.")
        return pdf_file

class SubjectForm(forms.ModelForm):
    class Meta:
        model = Subject
        fields = ['class_level', 'section', 'name', 'code', 'assigned_teacher', 'is_elective', 'is_active']
        widgets = {
            'class_level': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-white text-xs focus:ring-2 focus:ring-[#009688]'
            }),
            'section': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-white text-xs focus:ring-2 focus:ring-[#009688]'
            }),
            'name': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-white text-xs focus:ring-2 focus:ring-[#009688]',
                'placeholder': 'e.g. Mathematics'
            }),
            'code': forms.TextInput(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-white text-xs focus:ring-2 focus:ring-[#009688]',
                'placeholder': 'e.g. MATH-10'
            }),
            'assigned_teacher': forms.Select(attrs={
                'class': 'w-full px-3 py-2 bg-slate-950 border border-slate-700 rounded-xl text-white text-xs focus:ring-2 focus:ring-[#009688]'
            }),
            'is_elective': forms.CheckboxInput(attrs={
                'class': 'rounded bg-slate-950 border-slate-700 text-[#009688] focus:ring-0'
            }),
            'is_active': forms.CheckboxInput(attrs={
                'class': 'rounded bg-slate-950 border-slate-700 text-[#009688] focus:ring-0'
            }),
        }

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['section'].required = False
        self.fields['assigned_teacher'].required = False
        self.fields['assigned_teacher'].queryset = User.objects.filter(role=RoleChoices.TEACHER, is_active=True)
