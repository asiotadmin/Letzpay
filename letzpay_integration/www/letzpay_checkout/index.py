import frappe
import hashlib

def get_context(context):

    SALT = "4e9807cfc9ed4933" #Provided by Letzpay
    data={}
    data.update({'PAY_ID':'1071521128151253'}) #Provided by Letzpay
    data.update({'ORDER_ID':frappe.form_dict.token})
    data.update({'AMOUNT':'100'})
    data.update({'TXNTYPE':'SALE'})
    data.update({'CUST_NAME':'Amitosh'})
    data.update({'CUST_EMAIL':'amitosh@letzpay.com'})
    data.update({'CUST_PHONE':'7077626024'})
    data.update({'CUST_ID':'TEST1234567890'})
    data.update({'CURRENCY_CODE':'356'})
    data.update({'RETURN_URL':'http://127.0.0.1:8003/api/method/letzpay_integration.www.letzpay_checkout.index.get_api_data'}) #Merchant's return URL
    hashString=''
    for key in sorted(data.keys()):
            hashString+=("%s=%s~" % (key, data[key]))
    finalHashString = hashString[:-1]
    finalHashString+=SALT
    action = "https://uat.letzpay.com/pgui/jsp/paymentrequest" #Letzpay's payment request URL
    hashh = hashlib.sha256(finalHashString.encode())
    finalHash = hashh.hexdigest().upper()
    data.update({'hash':finalHash})
    # print(data, '>>>>>>>>')
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
