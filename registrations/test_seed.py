"""seed_demo phải chạy được (2 lần liên tiếp) và dữ liệu nhất quán."""
from io import StringIO

from django.core.management import call_command
from django.test import TestCase

from events.models import TicketType
from registrations.models import Ticket, TicketStatus, WaitlistEntry


class SeedDemoTests(TestCase):
    def test_seed_twice_consistent(self):
        call_command("seed_demo", stdout=StringIO())
        call_command("seed_demo", stdout=StringIO())      # chạy lại không nhân đôi
        self.assertEqual(WaitlistEntry.objects.count(), 3)
        self.assertFalse(Ticket.objects.filter(booking_ref="").exists())
        for tt in TicketType.objects.all():
            real = tt.tickets.exclude(status=TicketStatus.CANCELLED).count()
            self.assertEqual(tt.sold, real, tt)
