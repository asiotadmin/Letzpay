# Copyright (c) 2023, Stya and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from payments.utils import create_payment_gateway
from frappe import _
from frappe.integrations.utils import (
	create_request_log,
)
from frappe.model.document import Document
from frappe.utils import call_hook_method, cint, get_url

class LetzpaySettings(Document):
	supported_currencies = ["INR"]
	def validate(self):
		create_payment_gateway("Letzpay")
		call_hook_method("payment_gateway_enabled", gateway="Letzpay")

	def validate_transaction_currency(self, currency):
		if currency not in self.supported_currencies:
			frappe.throw(
				_(
					"Please select another payment method. Razorpay does not support transactions in currency '{0}'"
				).format(currency)
			)

	def get_payment_url(self, **kwargs):
		integration_request = create_request_log(kwargs, integration_type='Host',service_name="LetzPay")
		return get_url(f"./letzpay_checkout?token={integration_request.name}")

	def create_request(self, data):
		self.data = frappe._dict(data)

		try:
			self.integration_request = frappe.get_doc("Integration Request", self.data.token)
			self.integration_request.update_status(self.data, "Queued")
			return self.authorize_payment()

		except Exception:
			frappe.log_error(frappe.get_traceback())
			return {
				"redirect_to": frappe.redirect_to_message(
					_("Server Error"),
					_(
						"Seems issue with server's razorpay config. Don't worry, in case of failure amount will get refunded to your account."
					),
				),
				"status": 401,
			}

	def get_settings(self, data):
		settings = frappe._dict(
			{
				"api_key": self.api_key,
				"api_secret": self.get_password(fieldname="api_secret", raise_exception=False),
			}
		)

		if cint(data.get("notes", {}).get("use_sandbox")) or data.get("use_sandbox"):
			settings.update(
				{
					"api_key": frappe.conf.sandbox_api_key,
					"api_secret": frappe.conf.sandbox_api_secret,
				}
			)

		return settings

@frappe.whitelist(allow_guest=True)
def get_api_key():
	controller = frappe.get_doc("Letzpay Settings")
	return controller.api_key
