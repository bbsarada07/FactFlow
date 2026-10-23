# WhatsApp webhook fixtures

Request bodies in the format Twilio (form fields of an inbound WhatsApp message) and the Meta Cloud API
(`messages` webhook JSON) document for their webhooks. **All values are fake**: phone numbers are in a
fictional range, SIDs are zero-filled, and no real request or person is represented. Tests sign them with a
test auth token / app secret at run time (tests/test_whatsapp.py).
