from django import forms
from django.contrib.auth import get_user_model
from django.contrib.auth.models import Group
from .models import LibraryDocument


class MetadataForm(forms.ModelForm):
    tags = forms.CharField(required=False, max_length=1000, help_text='Comma-separated tags; at most 20.')

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['title'].widget.attrs['placeholder'] = 'e.g. Product strategy · Q4 research'
        self.fields['description'].widget.attrs['placeholder'] = 'A short summary to help your team find and understand this document…'
        self.fields['tags'].widget.attrs['placeholder'] = 'e.g. research, strategy, meeting notes'
        if self.instance and self.instance.pk:
            self.initial['tags'] = ', '.join(self.instance.tags)

    def clean_tags(self):
        tags = list(dict.fromkeys(tag.strip() for tag in self.cleaned_data['tags'].split(',') if tag.strip()))
        if len(tags) > 20 or any(len(tag) > 80 for tag in tags):
            raise forms.ValidationError('Use at most 20 tags, each no longer than 80 characters.')
        return tags

    class Meta:
        model = LibraryDocument
        fields = ['title', 'description', 'category', 'tags']
        widgets = {'description': forms.Textarea(attrs={'rows': 3})}


class UploadForm(MetadataForm):
    original = forms.FileField(
        label='Document', help_text='PDF, DOCX, TXT, Markdown, PNG, JPEG. Maximum 25 MB.',
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.docx,.txt,.md,.png,.jpg,.jpeg'}),
    )
    authority = forms.BooleanField(label='I have authority to upload this document and request its processing.')


class ReplacementForm(forms.Form):
    original = forms.FileField(
        label='Replacement document',
        widget=forms.ClearableFileInput(attrs={'accept': '.pdf,.docx,.txt,.md,.png,.jpg,.jpeg'}),
    )
    authority = forms.BooleanField(label='I have authority to upload and process this replacement.')


class SharingForm(forms.Form):
    visibility = forms.ChoiceField(choices=LibraryDocument._meta.get_field('visibility').choices)
    user = forms.ModelChoiceField(label='Person', queryset=get_user_model().objects.none(), required=False, empty_label='Select a person (optional)')
    group = forms.ModelChoiceField(queryset=Group.objects.none(), required=False, empty_label='Select a group (optional)', help_text='Choose one person or one group per grant, or leave both empty to update visibility only.')
    access_level = forms.ChoiceField(choices=[('read', 'Read'), ('edit', 'Edit')])

    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.fields['user'].queryset = get_user_model().objects.filter(is_active=True, is_staff=True).order_by('username')
        self.fields['group'].queryset = Group.objects.order_by('name')

    def clean(self):
        data = super().clean()
        if data.get('user') and data.get('group'):
            raise forms.ValidationError('Choose one person or one group per grant.')
        return data


class ClearanceForm(forms.Form):
    classification = forms.ChoiceField(choices=[('internal_standard', 'Standard internal data — Gemini permitted'), ('restricted_pii', 'Restricted personal/financial data — processing blocked')])
    reason = forms.CharField(
        label='Review rationale', max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Summarise your clearance decision without including private document text…'}),
        help_text='Record the review rationale, not document bodies or personal data.',
    )


class ReviewForm(forms.Form):
    reason = forms.CharField(
        label='Public-use review notes', max_length=1000,
        widget=forms.Textarea(attrs={'rows': 3, 'placeholder': 'Record the privacy, confidentiality and rights checks behind your decision…'}),
        help_text='Confirm privacy, confidentiality, licensing and redaction review. Do not include document text.',
    )


class GrantRemovalForm(forms.Form):
    grant_id = forms.IntegerField(min_value=1)
