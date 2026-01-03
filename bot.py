import os
import json
import logging
from datetime import datetime
from telegram import Update
from telegram.ext import Application, CommandHandler, MessageHandler, filters, ContextTypes
import anthropic
import base64
from reportlab.lib import colors
from reportlab.lib.pagesizes import A4
from reportlab.platypus import SimpleDocTemplate, Table, TableStyle, Paragraph, Spacer, PageBreak
from reportlab.lib.styles import getSampleStyleSheet, ParagraphStyle
from reportlab.lib.units import cm
from reportlab.lib.enums import TA_CENTER
from io import BytesIO

logging.basicConfig(format='%(asctime)s - %(name)s - %(levelname)s - %(message)s', level=logging.INFO)
logger = logging.getLogger(__name__)

TELEGRAM_TOKEN = os.getenv('TELEGRAM_TOKEN')
ANTHROPIC_API_KEY = os.getenv('ANTHROPIC_API_KEY')

client = anthropic.Anthropic(api_key=ANTHROPIC_API_KEY)

DATA_FILE = 'receipts_data.json'

def load_receipts():
    try:
        with open(DATA_FILE, 'r', encoding='utf-8') as f:
            return json.load(f)
    except FileNotFoundError:
        return []

def save_receipts(receipts):
    with open(DATA_FILE, 'w', encoding='utf-8') as f:
        json.dump(receipts, f, ensure_ascii=False, indent=2)

async def start(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text(
        "🚗 Bienvenue dans votre Tracker de Carburant !\n\n"
        "📸 Envoyez-moi une photo de votre ticket de caisse\n"
        "📊 Utilisez /total pour voir vos totaux mensuels\n"
        "📋 Utilisez /liste pour voir tous vos tickets\n"
        "📄 Utilisez /pdf pour générer un PDF\n"
        "🗑️ Utilisez /reset pour effacer toutes les données\n\n"
        "Je vais analyser automatiquement chaque ticket !"
    )

async def analyze_receipt_image(image_data):
    try:
        message = client.messages.create(
            model="claude-sonnet-4-20250514",
            max_tokens=1024,
            messages=[
                {
                    "role": "user",
                    "content": [
                        {
                            "type": "image",
                            "source": {
                                "type": "base64",
                                "media_type": "image/jpeg",
                                "data": image_data,
                            },
                        },
                        {
                            "type": "text",
                            "text": "Analyse ce ticket de station-service et extrait les informations. Réponds UNIQUEMENT avec un JSON: {\"date\": \"YYYY-MM-DD\", \"liters\": 0.00, \"price_per_liter\": 0.000, \"vat\": 0.00, \"total_price\": 0.00, \"fuel_type\": \"GAZOLE\"}"
                        }
                    ],
                }
            ],
        )
        
        response_text = message.content[0].text.strip()
        response_text = response_text.replace('```json', '').replace('```', '').strip()
        
        return json.loads(response_text)
    except Exception as e:
        logger.error(f"Erreur analyse: {e}")
        return None

async def handle_photo(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📸 Photo reçue ! Analyse en cours...")
    
    try:
        photo = update.message.photo[-1]
        file = await context.bot.get_file(photo.file_id)
        image_bytes = await file.download_as_bytearray()
        image_base64 = base64.b64encode(image_bytes).decode('utf-8')
        
        receipt_data = await analyze_receipt_image(image_base64)
        
        if not receipt_data:
            await update.message.reply_text("❌ Je n'ai pas pu analyser ce ticket.")
            return
        
        receipts = load_receipts()
        receipt_data['id'] = len(receipts) + 1
        receipt_data['timestamp'] = datetime.now().isoformat()
        receipts.append(receipt_data)
        save_receipts(receipts)
        
        date_obj = datetime.strptime(receipt_data['date'], '%Y-%m-%d')
        formatted_date = date_obj.strftime('%d/%m/%Y')
        
        response = f"""✅ Ticket analysé et ajouté !

📅 Date: {formatted_date}
⛽ Carburant: {receipt_data['fuel_type']}
📊 Quantité: {receipt_data['liters']:.2f} L
💶 Prix/L: {receipt_data['price_per_liter']:.3f} €
🧾 TVA: {receipt_data['vat']:.2f} €
💰 Total: {receipt_data['total_price']:.2f} €"""
        
        await update.message.reply_text(response)
        
    except Exception as e:
        logger.error(f"Erreur: {e}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")

async def show_total(update: Update, context: ContextTypes.DEFAULT_TYPE):
    receipts = load_receipts()
    
    if not receipts:
        await update.message.reply_text("📭 Aucun ticket enregistré.")
        return
    
    monthly_data = {}
    for receipt in receipts:
        date_obj = datetime.strptime(receipt['date'], '%Y-%m-%d')
        month_key = date_obj.strftime('%Y-%m')
        month_name = date_obj.strftime('%B %Y')
        
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                'name': month_name,
                'count': 0,
                'total_liters': 0,
                'total_vat': 0,
                'total_price': 0
            }
        
        monthly_data[month_key]['count'] += 1
        monthly_data[month_key]['total_liters'] += receipt['liters']
        monthly_data[month_key]['total_vat'] += receipt['vat']
        monthly_data[month_key]['total_price'] += receipt['total_price']
    
    response = "📊 TOTAUX MENSUELS\n" + "="*30 + "\n\n"
    
    for month_key in sorted(monthly_data.keys(), reverse=True):
        data = monthly_data[month_key]
        response += f"📅 {data['name']}\n"
        response += f"   • Tickets: {data['count']}\n"
        response += f"   • Litres: {data['total_liters']:.2f} L\n"
        response += f"   • TVA: {data['total_vat']:.2f} €\n"
        response += f"   • Total: {data['total_price']:.2f} €\n\n"
    
    total_tickets = len(receipts)
    total_liters = sum(r['liters'] for r in receipts)
    total_vat = sum(r['vat'] for r in receipts)
    total_price = sum(r['total_price'] for r in receipts)
    
    response += "="*30 + "\n"
    response += f"💰 TOTAL GÉNÉRAL\n"
    response += f"   • Tickets: {total_tickets}\n"
    response += f"   • Litres: {total_liters:.2f} L\n"
    response += f"   • TVA: {total_vat:.2f} €\n"
    response += f"   • Total: {total_price:.2f} €\n"
    
    await update.message.reply_text(response)

async def show_list(update: Update, context: ContextTypes.DEFAULT_TYPE):
    receipts = load_receipts()
    
    if not receipts:
        await update.message.reply_text("📭 Aucun ticket enregistré.")
        return
    
    response = "📋 LISTE DES TICKETS\n" + "="*30 + "\n\n"
    
    for receipt in sorted(receipts, key=lambda x: x['date'], reverse=True):
        date_obj = datetime.strptime(receipt['date'], '%Y-%m-%d')
        formatted_date = date_obj.strftime('%d/%m/%Y')
        response += f"#{receipt['id']} - {formatted_date}\n"
        response += f"   {receipt['fuel_type']} | {receipt['liters']:.2f}L | {receipt['total_price']:.2f}€\n\n"
    
    if len(response) > 4000:
        parts = [response[i:i+4000] for i in range(0, len(response), 4000)]
        for part in parts:
            await update.message.reply_text(part)
    else:
        await update.message.reply_text(response)

def generate_pdf(receipts, year=None):
    buffer = BytesIO()
    doc = SimpleDocTemplate(buffer, pagesize=A4, topMargin=2*cm, bottomMargin=2*cm)
    elements = []
    styles = getSampleStyleSheet()
    
    title_style = ParagraphStyle(
        'CustomTitle',
        parent=styles['Heading1'],
        fontSize=24,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=30,
        alignment=TA_CENTER,
        fontName='Helvetica-Bold'
    )
    
    subtitle_style = ParagraphStyle(
        'CustomSubtitle',
        parent=styles['Heading2'],
        fontSize=16,
        textColor=colors.HexColor('#1e40af'),
        spaceAfter=12,
        spaceBefore=20,
        fontName='Helvetica-Bold'
    )
    
    if year:
        receipts = [r for r in receipts if datetime.strptime(r['date'], '%Y-%m-%d').year == year]
        title_text = f"Rapport Carburant {year}"
    else:
        title_text = "Rapport Carburant - Tous les tickets"
    
    if not receipts:
        elements.append(Paragraph(title_text, title_style))
        elements.append(Spacer(1, 20))
        elements.append(Paragraph("Aucun ticket trouvé.", styles['Normal']))
        doc.build(elements)
        buffer.seek(0)
        return buffer
    
    elements.append(Paragraph(title_text, title_style))
    elements.append(Paragraph(f"Généré le {datetime.now().strftime('%d/%m/%Y')}", styles['Normal']))
    elements.append(Spacer(1, 30))
    
    monthly_data = {}
    for receipt in receipts:
        date_obj = datetime.strptime(receipt['date'], '%Y-%m-%d')
        month_key = date_obj.strftime('%Y-%m')
        month_name = date_obj.strftime('%B %Y').title()
        
        if month_key not in monthly_data:
            monthly_data[month_key] = {
                'name': month_name,
                'receipts': [],
                'totals': {'liters': 0, 'vat': 0, 'total_price': 0}
            }
        
        monthly_data[month_key]['receipts'].append(receipt)
        monthly_data[month_key]['totals']['liters'] += receipt['liters']
        monthly_data[month_key]['totals']['vat'] += receipt['vat']
        monthly_data[month_key]['totals']['total_price'] += receipt['total_price']
    
    for month_key in sorted(monthly_data.keys(), reverse=True):
        data = monthly_data[month_key]
        
        elements.append(Paragraph(data['name'], subtitle_style))
        elements.append(Spacer(1, 10))
        
        table_data = [['Date', 'Carburant', 'Litres', 'Prix/L', 'TVA', 'Total']]
        
        for receipt in sorted(data['receipts'], key=lambda x: x['date']):
            date_obj = datetime.strptime(receipt['date'], '%Y-%m-%d')
            table_data.append([
                date_obj.strftime('%d/%m/%Y'),
                receipt['fuel_type'],
                f"{receipt['liters']:.2f} L",
                f"{receipt['price_per_liter']:.3f} €",
                f"{receipt['vat']:.2f} €",
                f"{receipt['total_price']:.2f} €"
            ])
        
        table_data.append([
            'TOTAL',
            '',
            f"{data['totals']['liters']:.2f} L",
            '',
            f"{data['totals']['vat']:.2f} €",
            f"{data['totals']['total_price']:.2f} €"
        ])
        
        table = Table(table_data, colWidths=[3*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm, 2.5*cm])
        table.setStyle(TableStyle([
            ('BACKGROUND', (0, 0), (-1, 0), colors.HexColor('#1e40af')),
            ('TEXTCOLOR', (0, 0), (-1, 0), colors.whitesmoke),
            ('ALIGN', (0, 0), (-1, 0), 'CENTER'),
            ('FONTNAME', (0, 0), (-1, 0), 'Helvetica-Bold'),
            ('FONTSIZE', (0, 0), (-1, 0), 10),
            ('BACKGROUND', (0, 1), (-1, -2), colors.beige),
            ('ALIGN', (2, 1), (-1, -1), 'RIGHT'),
            ('FONTSIZE', (0, 1), (-1, -2), 9),
            ('GRID', (0, 0), (-1, -2), 1, colors.grey),
            ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#dbeafe')),
            ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ]))
        
        elements.append(table)
        elements.append(Spacer(1, 30))
    
    elements.append(PageBreak())
    elements.append(Paragraph("RÉSUMÉ ANNUEL", title_style))
    elements.append(Spacer(1, 20))
    
    total_tickets = len(receipts)
    total_liters = sum(r['liters'] for r in receipts)
    total_vat = sum(r['vat'] for r in receipts)
    total_price = sum(r['total_price'] for r in receipts)
    avg_price = total_price / total_liters if total_liters > 0 else 0
    
    summary_data = [
        ['Tickets', f"{total_tickets}"],
        ['Litres', f"{total_liters:.2f} L"],
        ['Prix moyen/L', f"{avg_price:.3f} €"],
        ['TVA', f"{total_vat:.2f} €"],
        ['TOTAL', f"{total_price:.2f} €"]
    ]
    
    summary_table = Table(summary_data, colWidths=[10*cm, 6*cm])
    summary_table.setStyle(TableStyle([
        ('BACKGROUND', (0, 0), (-1, -2), colors.beige),
        ('BACKGROUND', (0, -1), (-1, -1), colors.HexColor('#1e40af')),
        ('TEXTCOLOR', (0, -1), (-1, -1), colors.whitesmoke),
        ('ALIGN', (1, 0), (1, -1), 'RIGHT'),
        ('FONTNAME', (0, -1), (-1, -1), 'Helvetica-Bold'),
        ('FONTSIZE', (0, -1), (-1, -1), 14),
        ('GRID', (0, 0), (-1, -1), 1, colors.grey),
    ]))
    
    elements.append(summary_table)
    doc.build(elements)
    buffer.seek(0)
    return buffer

async def generate_pdf_command(update: Update, context: ContextTypes.DEFAULT_TYPE):
    await update.message.reply_text("📄 Génération du PDF...")
    
    try:
        receipts = load_receipts()
        
        if not receipts:
            await update.message.reply_text("📭 Aucun ticket enregistré !")
            return
        
        year = None
        if context.args and len(context.args) > 0:
            try:
                year = int(context.args[0])
            except ValueError:
                await update.message.reply_text("❌ Format invalide. Utilisez: /pdf ou /pdf 2025")
                return
        
        pdf_buffer = generate_pdf(receipts, year)
        
        if year:
            filename = f"rapport_carburant_{year}.pdf"
        else:
            filename = "rapport_carburant_complet.pdf"
        
        await update.message.reply_document(
            document=pdf_buffer,
            filename=filename,
            caption="✅ Votre rapport carburant ! 📊"
        )
        
    except Exception as e:
        logger.error(f"Erreur PDF: {e}")
        await update.message.reply_text(f"❌ Erreur: {str(e)}")

async def reset_data(update: Update, context: ContextTypes.DEFAULT_TYPE):
    try:
        save_receipts([])
        await update.message.reply_text("🗑️ Données effacées.")
    except Exception as e:
        await update.message.reply_text(f"❌ Erreur: {str(e)}")

async def error_handler(update: Update, context: ContextTypes.DEFAULT_TYPE):
    logger.error(f"Exception: {context.error}")
    if update and update.message:
        await update.message.reply_text("❌ Une erreur s'est produite.")

def main():
    if not TELEGRAM_TOKEN or not ANTHROPIC_API_KEY:
        logger.error("Tokens manquants!")
        return
    
    application = Application.builder().token(TELEGRAM_TOKEN).build()
    
    application.add_handler(CommandHandler("start", start))
    application.add_handler(CommandHandler("total", show_total))
    application.add_handler(CommandHandler("liste", show_list))
    application.add_handler(CommandHandler("pdf", generate_pdf_command))
    application.add_handler(CommandHandler("reset", reset_data))
    application.add_handler(MessageHandler(filters.PHOTO, handle_photo))
    application.add_error_handler(error_handler)
    
    logger.info("🤖 Bot démarré!")
    application.run_polling(allowed_updates=Update.ALL_TYPES)

if __name__ == '__main__':
    main()
