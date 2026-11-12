"""Presentation labels only; authorization and state transitions stay in services."""
from django import template

register = template.Library()


@register.filter
def library_state(value):
    return {
        'awaiting_clearance': 'Awaiting clearance', 'queued': 'Queued',
        'processing': 'Processing', 'ready': 'Ready', 'failed': 'Failed',
        'blocked': 'Blocked', 'pending': 'Awaiting review', 'approved': 'Approved',
        'not_reviewed': 'Internal only', 'rejected': 'Rejected', 'revoked': 'Revoked',
    }.get(value, 'Not available')


@register.filter
def library_action(value):
    return {
        'upload': 'Document uploaded', 'replace': 'New version uploaded',
        'metadata': 'Document details updated', 'share': 'Sharing updated',
        'remove_grant': 'Access removed', 'clear': 'Processing clearance reviewed',
        'block': 'Processing blocked', 'request_public': 'Public review requested',
        'approve': 'Public use approved', 'reject': 'Public use rejected',
        'revoke': 'Public approval revoked', 'retry': 'Processing retry requested',
        'processing_ready': 'Document processing completed', 'download': 'Original downloaded',
        'admin_view': 'Administrator opened document', 'admin_list': 'Administrator browsed document',
        'admin_retrieve': 'Administrator retrieved reference',
    }.get(value, 'Library activity')


@register.filter
def library_icon(value):
    return {'pdf': 'fa-file-pdf', 'docx': 'fa-file-word', 'png': 'fa-file-image',
            'jpg': 'fa-file-image', 'jpeg': 'fa-file-image'}.get(value, 'fa-file-lines')
