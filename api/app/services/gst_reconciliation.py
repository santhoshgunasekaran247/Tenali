import csv
from collections import defaultdict
from datetime import date
from decimal import Decimal, InvalidOperation
from io import StringIO

from fastapi import HTTPException
from sqlalchemy import text

HEADERS=["supplier_gstin","invoice_number","invoice_date","taxable_value","cgst","sgst","igst","cess"]


def reconcile_2b(db,company_id:str,csv_text:str,from_date:date,to_date:date):
    if from_date>to_date:
        raise HTTPException(422,"From date cannot follow To date")
    reader=csv.DictReader(StringIO(csv_text.lstrip('\ufeff')))
    if not reader.fieldnames or not set(HEADERS).issubset(reader.fieldnames):
        raise HTTPException(422,"Use the normalized GSTR-2B CSV template headers")
    imported=defaultdict(list)
    for index,row in enumerate(reader,start=2):
        if index>10001:
            raise HTTPException(422,"Maximum 10,000 rows per reconciliation")
        try:
            invoice_date=date.fromisoformat(row['invoice_date'].strip())
            amounts={key:Decimal(row[key].strip() or '0') for key in HEADERS[3:]}
            if any(not value.is_finite() or value<0 for value in amounts.values()):
                raise ValueError()
            gst=row['supplier_gstin'].strip().upper()
            number=row['invoice_number'].strip().upper()
            if len(gst)!=15 or not number:
                raise ValueError()
        except (ValueError,InvalidOperation,KeyError,AttributeError) as error:
            raise HTTPException(422,f"Invalid GSTIN, date or amount at CSV row {index}") from error
        if not from_date<=invoice_date<=to_date:
            raise HTTPException(422,f"CSV row {index} is outside the selected period")
        imported[(gst,number)].append({**amounts,"invoice_date":invoice_date})
    books=defaultdict(list)
    for row in db.execute(text("""select p.id,p.bill_number,p.purchase_date,p.subtotal,p.gst_total,v.gst_number
        from purchases p join parties v on v.id=p.vendor_party_id and v.company_id=p.company_id
        where p.company_id=:company and p.purchase_date between :from_date and :to_date
          and (p.cancelled_at is null or p.cancelled_at>:to_date)"""),{"company":company_id,"from_date":from_date,"to_date":to_date}).mappings():
        books[((row['gst_number'] or '').strip().upper(),(row['bill_number'] or '').strip().upper())].append(dict(row))
    rows=[]
    for key in sorted(set(imported)|set(books)):
        statement,ledger=imported[key],books[key]
        tax=sum((sum((item[name] for name in ['cgst','sgst','igst','cess']),Decimal('0')) for item in statement),Decimal('0'))
        book_tax=sum((item['gst_total'] for item in ledger),Decimal('0'))
        taxable=sum((item['taxable_value'] for item in statement),Decimal('0'))
        book_taxable=sum((item['subtotal'] for item in ledger),Decimal('0'))
        status='DUPLICATE_REVIEW' if len(statement)>1 or len(ledger)>1 else 'MISSING_IN_BOOKS' if not ledger else 'MISSING_IN_2B' if not statement else 'MATCHED' if abs(tax-book_tax)<=Decimal('.01') and abs(taxable-book_taxable)<=Decimal('.01') and statement[0]['invoice_date']==ledger[0]['purchase_date'] else 'MISMATCH'
        rows.append({'supplier_gstin':key[0],'invoice_number':key[1],'status':status,'books_taxable':str(book_taxable),'statement_taxable':str(taxable),'books_gst':str(book_tax),'statement_gst':str(tax),'gst_difference':str(tax-book_tax)})
    return {'items':rows,'counts':{status:sum(row['status']==status for row in rows) for status in ['MATCHED','MISMATCH','MISSING_IN_BOOKS','MISSING_IN_2B','DUPLICATE_REVIEW']},'working_paper_only':True,
            'limitations':['Normalized CSV input, not a GST-portal integration.','GSTINs use the current vendor master for legacy bills.','Matching does not determine ITC eligibility or file a return.']}