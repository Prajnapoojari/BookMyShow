from celery import shared_task
from django.core.mail import EmailMessage
from django.conf import settings


@shared_task(bind=True, max_retries=3, default_retry_delay=30)
def send_ticket_email(self, order_id):
    from .models import Booking
    from .ticket_utils import generate_ticket_pdf

    bookings = list(Booking.objects.filter(order_id=order_id, status='confirmed').select_related(
        'user', 'movie', 'theater', 'seat'
    ))

    if not bookings:
        return f"No confirmed bookings found for order {order_id}"

    user = bookings[0].user
    movie = bookings[0].movie

    pdf_bytes = generate_ticket_pdf(bookings)

    try:
        email = EmailMessage(
            subject=f"Your ticket for {movie.name}",
            body=f"Hi {user.username},\n\nThanks for booking with BookMySeat! Your ticket is attached.\n\nEnjoy the movie!",
            from_email=settings.DEFAULT_FROM_EMAIL,
            to=[user.email],
        )
        email.attach(f'ticket_{order_id}.pdf', pdf_bytes, 'application/pdf')
        email.send()
        return f"Ticket emailed to {user.email}"
    except Exception as exc:
        raise self.retry(exc=exc)