# Copyright (c) 2023, Stya and contributors
# For license information, please see license.txt

import frappe
from frappe.model.document import Document
from payments.utils import create_payment_gateway
import hashlib
import hmac
import json
from urllib.parse import urlencode
from frappe import _
from frappe.integrations.utils import (
	create_request_log,
	make_get_request,
	make_post_request,
)
from frappe.model.document import Document
from frappe.utils import call_hook_method, cint, get_timestamp, get_url

class LetzpaySettings(Document):
	def validate(self):
		create_payment_gateway("Letzpay")
		call_hook_method("payment_gateway_enabled", gateway="Letzpay")
		if not self.flags.ignore_mandatory:
			self.validate_letzpay_credentails()

	def validate_letzpay_credentails(self):
		if self.pay_id and self.salt and self.encryption_key:
			pass
			# try:
			# 	make_get_request(
			# 		url="https://api.razorpay.com/v1/payments",
			# 		auth=(
			# 			self.api_key,
			# 			self.get_password(fieldname="api_secret", raise_exception=False),
			# 		),
			# 	)
			# except Exception:
			# 	frappe.throw(_("Seems API Key or API Secret is wrong !!!"))

	def validate_transaction_currency(self, currency):
		if currency not in self.supported_currencies:
			frappe.throw(
				_(
					"Please select another payment method. Razorpay does not support transactions in currency '{0}'"
				).format(currency)
			)


	def get_payment_url(self, **kwargs):
		integration_request = create_request_log(kwargs, service_name="Razorpay")
		return get_url(f"./razorpay_checkout?token={integration_request.name}")

	def create_order(self, **kwargs):
		# Creating Orders https://razorpay.com/docs/api/orders/

		# convert rupees to paisa
		kwargs["amount"] *= 100

		# Create integration log
		integration_request = create_request_log(kwargs, service_name="Razorpay")

		# Setup payment options
		payment_options = {
			"amount": kwargs.get("amount"),
			"currency": kwargs.get("currency", "INR"),
			"receipt": kwargs.get("receipt"),
			"payment_capture": kwargs.get("payment_capture"),
		}
		if self.api_key and self.api_secret:
			try:
				order = make_post_request(
					"https://api.razorpay.com/v1/orders",
					auth=(
						self.api_key,
						self.get_password(fieldname="api_secret", raise_exception=False),
					),
					data=payment_options,
				)
				order["integration_request"] = integration_request.name
				return order  # Order returned to be consumed by razorpay.js
			except Exception:
				frappe.log(frappe.get_traceback())
				frappe.throw(_("Could not create razorpay order"))

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

	def authorize_payment(self):
		"""
		An authorization is performed when user’s payment details are successfully authenticated by the bank.
		The money is deducted from the customer’s account, but will not be transferred to the merchant’s account
		until it is explicitly captured by merchant.
		"""
		data = json.loads(self.integration_request.data)
		settings = self.get_settings(data)

		try:
			resp = make_get_request(
				f"https://api.razorpay.com/v1/payments/{self.data.razorpay_payment_id}",
				auth=(settings.api_key, settings.api_secret),
			)

			if resp.get("status") == "authorized":
				self.integration_request.update_status(data, "Authorized")
				self.flags.status_changed_to = "Authorized"

			elif resp.get("status") == "captured":
				self.integration_request.update_status(data, "Completed")
				self.flags.status_changed_to = "Completed"

			elif data.get("subscription_id"):
				if resp.get("status") == "refunded":
					# if subscription start date is in future then
					# razorpay refunds the amount after authorizing the card details
					# thus changing status to Verified

					self.integration_request.update_status(data, "Completed")
					self.flags.status_changed_to = "Verified"

			else:
				frappe.log_error(message=str(resp), title="Razorpay Payment not authorized")

		except Exception:
			frappe.log_error()

		status = frappe.flags.integration_request.status_code

		redirect_to = data.get("redirect_to") or None
		redirect_message = data.get("redirect_message") or None
		if self.flags.status_changed_to in ("Authorized", "Verified", "Completed"):
			if self.data.reference_doctype and self.data.reference_docname:
				custom_redirect_to = None
				try:
					frappe.flags.data = data
					custom_redirect_to = frappe.get_doc(
						self.data.reference_doctype, self.data.reference_docname
					).run_method("on_payment_authorized", self.flags.status_changed_to)

				except Exception:
					frappe.log_error(frappe.get_traceback())

				if custom_redirect_to:
					redirect_to = custom_redirect_to

			redirect_url = "payment-success?doctype={}&docname={}".format(
				self.data.reference_doctype, self.data.reference_docname
			)
		else:
			redirect_url = "payment-failed"

		if redirect_to:
			redirect_url += "&" + urlencode({"redirect_to": redirect_to})
		if redirect_message:
			redirect_url += "&" + urlencode({"redirect_message": redirect_message})

		return {"redirect_to": redirect_url, "status": status}

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



def capture_payment(is_sandbox=False, sanbox_response=None):
	"""
	Verifies the purchase as complete by the merchant.
	After capture, the amount is transferred to the merchant within T+3 days
	where T is the day on which payment is captured.

	Note: Attempting to capture a payment whose status is not authorized will produce an error.
	"""
	controller = frappe.get_doc("Razorpay Settings")

	for doc in frappe.get_all(
		"Integration Request",
		filters={"status": "Authorized", "integration_request_service": "Razorpay"},
		fields=["name", "data"],
	):
		try:
			if is_sandbox:
				resp = sanbox_response
			else:
				data = json.loads(doc.data)
				settings = controller.get_settings(data)

				resp = make_get_request(
					"https://api.razorpay.com/v1/payments/{}".format(data.get("razorpay_payment_id")),
					auth=(settings.api_key, settings.api_secret),
					data={"amount": data.get("amount")},
				)

				if resp.get("status") == "authorized":
					resp = make_post_request(
						"https://api.razorpay.com/v1/payments/{}/capture".format(
							data.get("razorpay_payment_id")
						),
						auth=(settings.api_key, settings.api_secret),
						data={"amount": data.get("amount")},
					)

			if resp.get("status") == "captured":
				frappe.db.set_value("Integration Request", doc.name, "status", "Completed")

		except Exception:
			doc = frappe.get_doc("Integration Request", doc.name)
			doc.status = "Failed"
			doc.error = frappe.get_traceback()
			doc.save()
			frappe.log_error(doc.error, f"{doc.name} Failed")

@frappe.whitelist(allow_guest=True)
def get_api_key():
	controller = frappe.get_doc("Letzpay Settings")
	return controller.api_key

@frappe.whitelist(allow_guest=True)
def get_order(doctype, docname):
	# Order returned to be consumed by razorpay.js
	doc = frappe.get_doc(doctype, docname)
	try:
		# Do not use run_method here as it fails silently
		return doc.get_razorpay_order()
	except AttributeError:
		frappe.log_error(
			frappe.get_traceback(), _("Controller method get_razorpay_order missing")
		)
		frappe.throw(_("Could not create Razorpay order. Please contact Administrator"))


@frappe.whitelist(allow_guest=True)
def order_payment_success(integration_request, params):
	"""Called by razorpay.js on order payment success, the params
	contains razorpay_payment_id, razorpay_order_id, razorpay_signature
	that is updated in the data field of integration request

	Args:
	        integration_request (string): Name for integration request doc
	        params (string): Params to be updated for integration request.
	"""
	params = json.loads(params)
	integration = frappe.get_doc("Integration Request", integration_request)

	# Update integration request
	integration.update_status(params, integration.status)
	integration.reload()

	data = json.loads(integration.data)
	controller = frappe.get_doc("Razorpay Settings")

	# Update payment and integration data for payment controller object
	controller.integration_request = integration
	controller.data = frappe._dict(data)

	# Authorize payment
	controller.authorize_payment()