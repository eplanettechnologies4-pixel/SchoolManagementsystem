import datetime
from abc import ABC, abstractmethod
from decimal import Decimal
from django.db import transaction
from django.utils import timezone
from accounts.services import log_audit
from fees.models import Payment, PaymentMethod, ChallanStatusChoices


class PaymentGateway(ABC):
    """
    Abstract interface for payment gateway integrations.
    Future providers (JazzCash, EasyPaisa, Stripe, etc.) must implement this interface.
    """

    @abstractmethod
    def process_payment(self, challan, amount, received_by=None, reference_no=None, notes=None, request=None) -> Payment:
        """
        Process a payment against a given Challan.
        """
        pass

    @abstractmethod
    def reverse_payment(self, payment: Payment, reason: str, user=None, request=None) -> Payment:
        """
        Reverse a previously recorded payment by creating an immutable reversal entry.
        """
        pass

    @abstractmethod
    def get_gateway_name(self) -> str:
        """
        Return human-readable gateway title.
        """
        pass


class VirtualGateway(PaymentGateway):
    """
    Virtual Simulated Gateway for manual testing and placeholder payments.
    Marks transactions with clear VIRTUAL / TEST indicators and maintains immutability.
    """

    def get_gateway_name(self) -> str:
        return "Virtual Gateway (SIMULATION / TEST ONLY)"

    @transaction.atomic
    def process_payment(self, challan, amount, received_by=None, reference_no=None, notes=None, request=None) -> Payment:
        from fees.models import Challan, Payment
        # Lock challan row for concurrency safety
        challan = Challan.objects.select_for_update().get(pk=challan.pk)

        amount = Decimal(str(amount))
        if amount <= Decimal('0.00'):
            raise ValueError("Payment amount must be strictly greater than zero.")

        # Generate unique reference_no if not provided
        if not reference_no:
            prefix = timezone.now().strftime('VIR-%Y%m-')
            last_payment = Payment.all_objects.filter(reference_no__startswith=prefix).order_by('-id').first()
            if last_payment and last_payment.reference_no:
                try:
                    last_seq = int(last_payment.reference_no.split('-')[-1])
                    seq = last_seq + 1
                except ValueError:
                    seq = Payment.all_objects.count() + 1
            else:
                seq = 1
            reference_no = f"{prefix}{seq:04d}"

        payment = Payment.objects.create(
            school=challan.school,
            challan=challan,
            amount=amount,
            method=PaymentMethod.VIRTUAL,
            reference_no=reference_no,
            received_by=received_by,
            received_at=timezone.now(),
            is_virtual=True,
            is_reversal=False,
            notes=notes or "Manually marked as Virtual Paid (Test Mode)"
        )

        # Audit log entry
        log_audit(
            user=received_by,
            action='PAYMENT',
            instance=payment,
            changes={
                'challan_no': challan.challan_no,
                'amount': float(amount),
                'method': PaymentMethod.VIRTUAL,
                'reference_no': reference_no,
                'is_virtual': True
            },
            request=request,
            school=challan.school
        )

        return payment

    @transaction.atomic
    def reverse_payment(self, payment: Payment, reason: str, user=None, request=None) -> Payment:
        from fees.models import Challan, Payment
        if payment.is_reversal:
            raise ValueError("A reversal entry cannot be reversed again.")

        # Lock challan
        challan = Challan.objects.select_for_update().get(pk=payment.challan_id)

        prefix = timezone.now().strftime('REV-%Y%m-')
        last_rev = Payment.all_objects.filter(reference_no__startswith=prefix).order_by('-id').first()
        if last_rev and last_rev.reference_no:
            try:
                last_seq = int(last_rev.reference_no.split('-')[-1])
                seq = last_seq + 1
            except ValueError:
                seq = Payment.all_objects.count() + 1
        else:
            seq = 1
        rev_ref = f"{prefix}{seq:04d}"

        # Reversal creates a negative amount entry
        reversal_payment = Payment.objects.create(
            school=challan.school,
            challan=challan,
            amount=-payment.amount,
            method=payment.method,
            reference_no=rev_ref,
            received_by=user,
            received_at=timezone.now(),
            is_virtual=payment.is_virtual,
            is_reversal=True,
            reversal_of=payment,
            notes=f"Reversal of {payment.reference_no}. Reason: {reason}"
        )

        log_audit(
            user=user,
            action='REVERSAL',
            instance=reversal_payment,
            changes={
                'reversal_of': payment.reference_no,
                'reversed_amount': float(payment.amount),
                'reason': reason
            },
            request=request,
            school=challan.school
        )

        return reversal_payment

