# -*- coding: utf-8 -*-
from logging import getLogger
from openprocurement.api.utils import opresource
from openprocurement.api.views.award import TenderAwardResource
from openprocurement.api.models import Contract, STAND_STILL_TIME, get_now
from openprocurement.api.utils import (
    apply_patch,
    save_tender,
    json_view,
    context_unpack,
)
from openprocurement.api.validation import (
    validate_patch_award_data,
)
from openprocurement.tender.openua.utils import add_next_award

LOGGER = getLogger(__name__)


@opresource(name='Tender UA Awards',
            collection_path='/tenders/{tender_id}/awards',
            path='/tenders/{tender_id}/awards/{award_id}',
            description="Tender awards",
            procurementMethodType='aboveThresholdUA')
class TenderUaAwardResource(TenderAwardResource):

    @json_view(content_type="application/json", permission='edit_tender', validators=(validate_patch_award_data,))
    def patch(self):
        """Update of award

        Example request to change the award:

        .. sourcecode:: http

            PATCH /tenders/4879d3f8ee2443169b5fbbc9f89fa607/awards/71b6c23ed8944d688e92a31ec8c3f61a HTTP/1.1
            Host: example.com
            Accept: application/json

            {
                "data": {
                    "value": {
                        "amount": 600
                    }
                }
            }

        And here is the response to be expected:

        .. sourcecode:: http

            HTTP/1.0 200 OK
            Content-Type: application/json

            {
                "data": {
                    "id": "4879d3f8ee2443169b5fbbc9f89fa607",
                    "date": "2014-10-28T11:44:17.947Z",
                    "status": "active",
                    "suppliers": [
                        {
                            "id": {
                                "name": "Державне управління справами",
                                "scheme": "https://ns.openprocurement.org/ua/edrpou",
                                "uid": "00037256",
                                "uri": "http://www.dus.gov.ua/"
                            },
                            "address": {
                                "countryName": "Україна",
                                "postalCode": "01220",
                                "region": "м. Київ",
                                "locality": "м. Київ",
                                "streetAddress": "вул. Банкова, 11, корпус 1"
                            }
                        }
                    ],
                    "value": {
                        "amount": 600,
                        "currency": "UAH",
                        "valueAddedTaxIncluded": true
                    }
                }
            }

        """
        tender = self.request.validated['tender']
        if tender.status not in ['active.qualification', 'active.awarded']:
            self.request.errors.add('body', 'data', 'Can\'t update award in current ({}) tender status'.format(tender.status))
            self.request.errors.status = 403
            return
        award = self.request.context
        if any([i.status != 'active' for i in tender.lots if i.id == award.lotID]):
            self.request.errors.add('body', 'data', 'Can update award only in active lot status')
            self.request.errors.status = 403
            return
        award_status = award.status
        apply_patch(self.request, save=False, src=self.request.context.serialize())
        if award_status == 'pending' and award.status == 'active':
            award.complaintPeriod.endDate = get_now() + STAND_STILL_TIME
            tender.contracts.append(Contract({'awardID': award.id}))
            add_next_award(self.request)
        elif award_status == 'active' and award.status == 'cancelled':
            award.complaintPeriod.endDate = get_now()
            for i in tender.contracts:
                if i.awardID == award.id:
                    i.status = 'cancelled'
            add_next_award(self.request)
        elif award_status == 'pending' and award.status == 'unsuccessful':
            award.complaintPeriod.endDate = get_now() + STAND_STILL_TIME
            add_next_award(self.request)
        elif award_status == 'unsuccessful' and award.status == 'cancelled' and any([i.status in ['claim', 'answered', 'pending', 'resolved'] for i in award.complaints]):
            if tender.status == 'active.awarded':
                tender.status = 'active.qualification'
                tender.awardPeriod.endDate = None
            now = get_now()
            award.complaintPeriod.endDate = now
            cancelled_awards = []
            for i in tender.awards[tender.awards.index(award):]:
                if i.lotID != award.lotID:
                    continue
                i.complaintPeriod.endDate = now
                i.status = 'cancelled'
                for j in i.complaints:
                    if j.status != ['invalid', 'resolved', 'declined']:
                        j.status = 'cancelled'
                        j.cancellationReason = 'cancelled'
                        j.dateCanceled = now
                cancelled_awards.append(i.id)
            for i in tender.contracts:
                if i.awardID in cancelled_awards:
                    i.status = 'cancelled'
            add_next_award(self.request)
        else:
            self.request.errors.add('body', 'data', 'Can\'t update award in current ({}) status'.format(award_status))
            self.request.errors.status = 403
            return
        if save_tender(self.request):
            LOGGER.info('Updated tender award {}'.format(self.request.context.id),
                        extra=context_unpack(self.request, {'MESSAGE_ID': 'tender_award_patch'}, {'TENDER_REV': tender.rev}))
            return {'data': award.serialize("view")}