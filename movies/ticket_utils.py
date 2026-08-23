import io
import qrcode
from reportlab.lib.pagesizes import A5
from reportlab.pdfgen import canvas
from reportlab.lib.units import mm


def generate_ticket_pdf(bookings):
    """
    Takes a list of confirmed Booking objects (all from the same order)
    and returns a PDF file as bytes, ready to attach to an email or download.
    """
    first_booking = bookings[0]
    movie = first_booking.movie
    theater = first_booking.theater
    seat_numbers = ', '.join(b.seat.seat_number for b in bookings)
    order_id = first_booking.order_id

    buffer = io.BytesIO()
    pdf = canvas.Canvas(buffer, pagesize=A5)
    width, height = A5

    # --- Title ---
    pdf.setFont("Helvetica-Bold", 16)
    pdf.drawString(15 * mm, height - 20 * mm, "BookMySeat - Movie Ticket")

    # --- Movie & show details ---
    pdf.setFont("Helvetica", 11)
    y = height - 35 * mm
    line_height = 7 * mm

    details = [
        f"Movie: {movie.name}",
        f"Theater / Screen: {theater.name}",
        f"Show Time: {theater.time.strftime('%d %b %Y, %I:%M %p')}",
        f"Seats: {seat_numbers}",
        f"Booking ID: {order_id}",
        f"Payment Reference: {order_id}",  # placeholder until real payment IDs exist
    ]
    for line in details:
        pdf.drawString(15 * mm, y, line)
        y -= line_height

    # --- QR code, for verification at the theater entrance ---
    qr_img = qrcode.make(str(order_id))
    qr_buffer = io.BytesIO()
    qr_img.save(qr_buffer, format='PNG')
    qr_buffer.seek(0)
    from reportlab.lib.utils import ImageReader
    pdf.drawImage(ImageReader(qr_buffer), 15 * mm, y - 35 * mm, width=30 * mm, height=30 * mm)

    pdf.setFont("Helvetica-Oblique", 8)
    pdf.drawString(50 * mm, y - 20 * mm, "Scan this QR code at the theater entrance")

    pdf.showPage()
    pdf.save()

    buffer.seek(0)
    return buffer.read()