from unittest.mock import patch
from django.test import TestCase
from django.core import mail
from django.db import transaction
from accounts.models import User
from notifications.models import Notification, NotificationKind
from notifications.services import notify, notify_on_commit, notify_many

class NotificationServiceTest(TestCase):
    def setUp(self):
        self.user1 = User.objects.create_user(username="user1", email="user1@example.com")
        self.user2 = User.objects.create_user(username="user2", email="")
        
    @patch('notifications.services.send_templated_email')
    def test_t7_0_1_notify_with_template(self, mock_send):
        notify(self.user1, NotificationKind.TASK_ASSIGNED, "Title", "Msg", email_template="fake_tpl")
        self.assertEqual(Notification.objects.count(), 1)
        mock_send.assert_called_once()
        
    @patch('notifications.services.send_templated_email')
    def test_t7_0_2_no_email(self, mock_send):
        notify(self.user2, NotificationKind.TASK_ASSIGNED, "Title", "Msg", email_template="fake_tpl")
        self.assertEqual(Notification.objects.count(), 1)
        mock_send.assert_not_called()
        
    @patch('notifications.services.send_templated_email')
    def test_t7_0_3_email_error_handled(self, mock_send):
        mock_send.side_effect = Exception("SMTP Error")
        notify(self.user1, NotificationKind.TASK_ASSIGNED, "Title", "Msg", email_template="fake_tpl")
        self.assertEqual(Notification.objects.count(), 1)
        
    @patch('notifications.services.notify')
    def test_t7_0_4_rollback_on_commit(self, mock_notify):
        try:
            with transaction.atomic():
                notify_on_commit(self.user1, NotificationKind.TASK_ASSIGNED, "Title", "Msg")
                raise ValueError("Abort")
        except ValueError:
            pass
            
        mock_notify.assert_not_called()
        self.assertEqual(Notification.objects.count(), 0)
        
        # Test success case
        with self.captureOnCommitCallbacks(execute=True):
            with transaction.atomic():
                notify_on_commit(self.user1, NotificationKind.TASK_ASSIGNED, "Title", "Msg")
        mock_notify.assert_called_once()
