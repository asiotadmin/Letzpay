import frappe
import hashlib
from frappe.utils import cint

def get_context(context):
    data={}
    query_params = frappe.form_dict
    integraton_req = frappe.get_doc('Integration Request',query_params.get('token'))
    letz_perams = frappe.get_doc('Letzpay Settings')
    SALT = letz_perams.salt #Provided by Letzpay
    payment_req_doc = frappe.get_doc('Payment Request',integraton_req.reference_docname)
    sales_doc = frappe.get_doc('Sales Invoice', payment_req_doc.reference_name )
    contact_detail = frappe.get_doc('Contact', sales_doc.contact_person)
    data.update({'PAY_ID':letz_perams.pay_id}) #Provided by Letzpay
    data.update({'ORDER_ID':frappe.form_dict.token})
    data.update({'AMOUNT':cint(sales_doc.grand_total * 100)})
    data.update({'TXNTYPE':letz_perams.txntype})
    data.update({'CUST_NAME':sales_doc.customer_name})
    data.update({'CUST_EMAIL':contact_detail.email_id})
    data.update({'CUST_PHONE':contact_detail.mobile_no})
    data.update({'CUST_ID':sales_doc.customer})
    data.update({'CURRENCY_CODE':letz_perams.currency_code})
    data.update({'RETURN_URL':f'{frappe.utils.get_url()}/api/method/letzpay_integration.www.letzpay_checkout.index.get_api_data'}) #Merchant's return URL
    hashString=''
    for key in sorted(data.keys()):
            hashString+=("%s=%s~" % (key, data[key]))
    finalHashString = hashString[:-1]
    finalHashString+=SALT
    action = "https://uat.letzpay.com/pgui/jsp/paymentrequest" #Letzpay's payment request URL
    hashh = hashlib.sha256(finalHashString.encode())
    finalHash = hashh.hexdigest().upper()
    data.update({'hash':finalHash})
    context.data = data
    context.action = action

import json
@frappe.whitelist(allow_guest=True)
def get_api_data(**kwargs):
    data = kwargs.get('ORDER_ID')
    doc = frappe.get_doc('Integration Request',data)
    frappe.get_doc({"doctype":'Integration Request',
                    "integration_type":"Host",
                    "data":json.dumps(kwargs),
                    "integration_request_service":"LetzPay",
                    "status":"Authorized",
                    "reference_doctype": doc.reference_doctype,
                    "reference_docname":doc.reference_docname
    }).insert(ignore_permissions=True)

    if kwargs.get('STATUS') == "Captured":
        redirect =frappe.get_doc(doc.reference_doctype,doc.reference_docname).run_method('on_payment_authorized','Completed')
        frappe.local.response['type'] = "redirect"
        frappe.local.response['location'] = '/integrations/payment-success'     

    else:
        frappe.local.response['type'] = "redirect"
        frappe.local.response['location'] = '/integrations/payment-failed'   
