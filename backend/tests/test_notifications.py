"""
Tests for email notifications module.
"""

import pytest
import os
from unittest.mock import patch, MagicMock, call
from notifications import (
    send_email,
    notify_match_found,
    notify_bid_received,
    notify_bid_accepted,
    notify_transaction_completed,
    NOTIFICATIONS_ENABLED,
    SMTP_USERNAME
)


class TestSendEmailBasics:
    """Test basic email sending functionality."""

    @patch('notifications.smtplib.SMTP')
    def test_send_email_success(self, mock_smtp):
        """Test successful email sending"""
        mock_server = MagicMock()
        mock_smtp.return_value.__enter__.return_value = mock_server

        # Mock environment for enabled notifications
        with patch.dict(os.environ, {'NOTIFICATIONS_ENABLED': 'true', 'SMTP_USERNAME': 'test@example.com'}):
            with patch('notifications.NOTIFICATIONS_ENABLED', True):
                with patch('notifications.SMTP_USERNAME', 'test@example.com'):
                    result = send_email(
                        to_email="recipient@example.com",
                        subject="Test Subject",
                        html_content="<h1>Test</h1>",
                        text_content="Test"
                    )

        assert result is True
        mock_server.starttls.assert_called_once()
        mock_server.login.assert_called_once()
        mock_server.send_message.assert_called_once()

    def test_send_email_disabled_notifications(self):
        """Test email sending when notifications are disabled"""
        with patch('notifications.NOTIFICATIONS_ENABLED', False):
            result = send_email(
                to_email="recipient@example.com",
                subject="Test",
                html_content="<h1>Test</h1>"
            )

        assert result is False

    def test_send_email_no_smtp_configured(self):
        """Test email sending when SMTP is not configured"""
        with patch('notifications.NOTIFICATIONS_ENABLED', True):
            with patch('notifications.SMTP_USERNAME', ''):
                result = send_email(
                    to_email="recipient@example.com",
                    subject="Test",
                    html_content="<h1>Test</h1>"
                )

        assert result is False

    @patch('notifications.smtplib.SMTP')
    def test_send_email_smtp_error(self, mock_smtp):
        """Test email sending handles SMTP errors"""
        mock_smtp.side_effect = Exception("SMTP connection failed")

        with patch('notifications.NOTIFICATIONS_ENABLED', True):
            with patch('notifications.SMTP_USERNAME', 'test@example.com'):
                result = send_email(
                    to_email="recipient@example.com",
                    subject="Test",
                    html_content="<h1>Test</h1>"
                )

        assert result is False


class TestNotifyMatchFound:
    """Test match found notification."""

    @patch('notifications.send_email')
    def test_notify_match_found_structure(self, mock_send):
        """Test that match found notification has correct structure"""
        mock_send.return_value = True

        result = notify_match_found(
            generator_email="gen@example.com",
            generator_name="Generator Inc",
            receptor_name="Receptor Ltd",
            product="Manzanas",
            quantity_kg=100.0,
            match_score=0.85
        )

        assert result is True
        assert mock_send.called
        call_args = mock_send.call_args

        # Check parameters
        assert call_args[1]['to_email'] == "gen@example.com"
        assert call_args[1]['subject'] == "AEGIS-FOOD: Nuevo Comprador Compatible - Receptor Ltd"
        assert "Generator Inc" in call_args[1]['html_content']
        assert "Receptor Ltd" in call_args[1]['html_content']
        assert "Manzanas" in call_args[1]['html_content']
        assert "100.0" in call_args[1]['html_content']
        assert "85" in call_args[1]['html_content']  # match score %

    @patch('notifications.send_email')
    def test_notify_match_found_includes_product_details(self, mock_send):
        """Test notification includes all product details"""
        mock_send.return_value = True

        notify_match_found(
            generator_email="gen@example.com",
            generator_name="Test Gen",
            receptor_name="Test Rec",
            product="Tomatoes",
            quantity_kg=250.0,
            match_score=0.95
        )

        html = mock_send.call_args[1]['html_content']
        assert "Tomatoes" in html
        assert "250.0" in html
        assert "95" in html


class TestNotifyBidReceived:
    """Test bid received notification."""

    @patch('notifications.send_email')
    def test_notify_bid_received_structure(self, mock_send):
        """Test bid received notification structure"""
        mock_send.return_value = True

        result = notify_bid_received(
            generator_email="gen@example.com",
            generator_name="Generator Corp",
            receptor_name="Receptor Corp",
            product="Naranjas",
            bid_price=45.50,
            bid_quantity=200.0
        )

        assert result is True
        call_args = mock_send.call_args

        assert call_args[1]['to_email'] == "gen@example.com"
        assert "Nueva Oferta Recibida" in call_args[1]['subject']
        assert "Naranjas" in call_args[1]['subject']
        assert "Generator Corp" in call_args[1]['html_content']
        assert "Receptor Corp" in call_args[1]['html_content']
        assert "45.50" in call_args[1]['html_content']
        assert "200.0" in call_args[1]['html_content']

    @patch('notifications.send_email')
    def test_notify_bid_received_email_formatting(self, mock_send):
        """Test that bid received email is properly formatted"""
        mock_send.return_value = True

        notify_bid_received(
            generator_email="test@test.com",
            generator_name="Test",
            receptor_name="Test Receptor",
            product="Test Product",
            bid_price=100.0,
            bid_quantity=50.0
        )

        html = mock_send.call_args[1]['html_content']
        text = mock_send.call_args[1]['text_content']

        # Check HTML formatting
        assert "<html>" in html or "<body>" in html
        assert "Test Receptor" in html

        # Check text content exists
        assert text is not None
        assert "Test Receptor" in text


class TestNotifyBidAccepted:
    """Test bid accepted notification."""

    @patch('notifications.send_email')
    def test_notify_bid_accepted_structure(self, mock_send):
        """Test bid accepted notification structure"""
        mock_send.return_value = True

        result = notify_bid_accepted(
            receptor_email="rec@example.com",
            receptor_name="Receptor Name",
            generator_name="Generator Name",
            product="Platanos",
            final_price=55.75,
            quantity_kg=150.0,
            transaction_id=12345
        )

        assert result is True
        call_args = mock_send.call_args

        assert call_args[1]['to_email'] == "rec@example.com"
        assert "aceptada" in call_args[1]['subject'].lower()
        assert "Platanos" in call_args[1]['subject']
        assert "Receptor Name" in call_args[1]['html_content']
        assert "Generator Name" in call_args[1]['html_content']
        assert "55.75" in call_args[1]['html_content']
        assert "150.0" in call_args[1]['html_content']
        assert "12345" in call_args[1]['html_content']

    @patch('notifications.send_email')
    def test_notify_bid_accepted_includes_transaction_id(self, mock_send):
        """Test that transaction ID is included"""
        mock_send.return_value = True

        notify_bid_accepted(
            receptor_email="test@test.com",
            receptor_name="Test",
            generator_name="Gen",
            product="Product",
            final_price=50.0,
            quantity_kg=100.0,
            transaction_id=99999
        )

        html = mock_send.call_args[1]['html_content']
        assert "99999" in html


class TestNotifyTransactionCompleted:
    """Test transaction completed notification."""

    @patch('notifications.send_email')
    def test_notify_transaction_completed_sends_to_both_parties(self, mock_send):
        """Test that notification is sent to both generator and receptor"""
        mock_send.return_value = True

        result = notify_transaction_completed(
            generator_email="gen@example.com",
            receptor_email="rec@example.com",
            generator_name="Generator",
            receptor_name="Receptor",
            product="Peras",
            quantity_kg=120.0,
            final_price=60.0,
            co2_avoided_kg=96.0,
            transaction_id=54321
        )

        assert result is True
        # Should be called twice (once for each party)
        assert mock_send.call_count == 2

    @patch('notifications.send_email')
    def test_notify_transaction_completed_includes_co2_impact(self, mock_send):
        """Test that CO2 impact is included"""
        mock_send.return_value = True

        notify_transaction_completed(
            generator_email="gen@example.com",
            receptor_email="rec@example.com",
            generator_name="Gen",
            receptor_name="Rec",
            product="Product",
            quantity_kg=100.0,
            final_price=50.0,
            co2_avoided_kg=50.0,
            transaction_id=123
        )

        # Check that both calls include CO2 info
        for call_item in mock_send.call_args_list:
            html = call_item[1]['html_content']
            assert "50.0" in html or "50" in html  # CO2 amount

    @patch('notifications.send_email')
    def test_notify_transaction_completed_structure(self, mock_send):
        """Test transaction completed notification structure"""
        mock_send.return_value = True

        result = notify_transaction_completed(
            generator_email="gen@test.com",
            receptor_email="rec@test.com",
            generator_name="Test Gen",
            receptor_name="Test Rec",
            product="Test Product",
            quantity_kg=200.0,
            final_price=100.0,
            co2_avoided_kg=160.0,
            transaction_id=55555
        )

        assert result is True

        # First call is to generator
        first_call_html = mock_send.call_args_list[0][1]['html_content']
        assert "Test Gen" in first_call_html or "Test Rec" in first_call_html

        # Second call is to receptor
        second_call_html = mock_send.call_args_list[1][1]['html_content']
        assert "Test Gen" in second_call_html or "Test Rec" in second_call_html


class TestNotificationTypes:
    """Test different notification types."""

    @patch('notifications.send_email')
    def test_all_notification_types_supported(self, mock_send):
        """Test that all notification types are implemented"""
        mock_send.return_value = True

        # Test match found
        result1 = notify_match_found(
            "test@test.com", "Gen", "Rec", "Product", 100, 0.8
        )
        assert result1 is True

        # Test bid received
        result2 = notify_bid_received(
            "test@test.com", "Gen", "Rec", "Product", 50, 100
        )
        assert result2 is True

        # Test bid accepted
        result3 = notify_bid_accepted(
            "test@test.com", "Rec", "Gen", "Product", 50, 100, 1
        )
        assert result3 is True

        # Test transaction completed
        result4 = notify_transaction_completed(
            "gen@test.com", "rec@test.com", "Gen", "Rec", "Product",
            100, 50, 50, 1
        )
        assert result4 is True


class TestEmailFormatting:
    """Test email content formatting."""

    @patch('notifications.send_email')
    def test_match_found_html_well_formatted(self, mock_send):
        """Test match found email has valid HTML"""
        mock_send.return_value = True

        notify_match_found(
            "test@test.com", "Gen", "Rec", "Product", 100, 0.8
        )

        html = mock_send.call_args[1]['html_content']
        # Check for HTML structure
        assert "<html>" in html or "<body>" in html
        assert "</html>" in html or "</body>" in html
        assert "<h2>" in html or "<h1>" in html

    @patch('notifications.send_email')
    def test_bid_received_html_well_formatted(self, mock_send):
        """Test bid received email has valid HTML"""
        mock_send.return_value = True

        notify_bid_received(
            "test@test.com", "Gen", "Rec", "Product", 50, 100
        )

        html = mock_send.call_args[1]['html_content']
        assert "<html>" in html or "<body>" in html
        assert "<ul>" in html or "<li>" in html

    @patch('notifications.send_email')
    def test_email_includes_text_fallback(self, mock_send):
        """Test that all notifications include plain text fallback"""
        mock_send.return_value = True

        # Test match found
        notify_match_found(
            "test@test.com", "Gen", "Rec", "Product", 100, 0.8
        )
        assert mock_send.call_args[1]['text_content'] is not None

        # Reset mock
        mock_send.reset_mock()

        # Test bid received
        notify_bid_received(
            "test@test.com", "Gen", "Rec", "Product", 50, 100
        )
        assert mock_send.call_args[1]['text_content'] is not None


class TestNotificationErrorHandling:
    """Test error handling in notifications."""

    @patch('notifications.send_email')
    def test_notify_match_found_handles_send_failure(self, mock_send):
        """Test that match notification handles send failures"""
        mock_send.return_value = False

        result = notify_match_found(
            "test@test.com", "Gen", "Rec", "Product", 100, 0.8
        )

        assert result is False

    @patch('notifications.send_email')
    def test_notify_transaction_completed_partial_failure(self, mock_send):
        """Test transaction notification handles partial failures"""
        # First call succeeds, second fails
        mock_send.side_effect = [True, False]

        result = notify_transaction_completed(
            "gen@test.com", "rec@test.com", "Gen", "Rec", "Product",
            100, 50, 50, 1
        )

        # Result should be False (not fully successful)
        assert result is False

    @patch('notifications.send_email')
    def test_notify_transaction_completed_both_succeed(self, mock_send):
        """Test transaction notification with both sends succeeding"""
        mock_send.return_value = True

        result = notify_transaction_completed(
            "gen@test.com", "rec@test.com", "Gen", "Rec", "Product",
            100, 50, 50, 1
        )

        assert result is True
