import csv
import uuid
import razorpay
from django.conf import settings
from .tasks import send_ticket_email
from django.http import HttpResponse
from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect, get_object_or_404
from .models import Movie,Theater,Seat,Booking,Review,Payment
from django.db import models
from django.db.models import Count, Sum
from django.core.paginator import Paginator
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.contrib import messages
from datetime import timedelta

@staff_member_required
def admin_dashboard(request):
    now = timezone.now()
    today_start = now.replace(hour=0, minute=0, second=0, microsecond=0)
    week_start = today_start - timedelta(days=today_start.weekday())
    month_start = today_start.replace(day=1)
    year_start = today_start.replace(month=1, day=1)

    range_start = request.GET.get('start_date', '')
    range_end = request.GET.get('end_date', '')

    confirmed = Booking.objects.filter(status='confirmed')
    range_bookings = confirmed
    if range_start:
        range_bookings = range_bookings.filter(booked_at__date__gte=range_start)
    if range_end:
        range_bookings = range_bookings.filter(booked_at__date__lte=range_end)

    range_revenue = range_bookings.aggregate(total=Sum('theater__ticket_price'))['total'] or 0
    range_count = range_bookings.count()

    def revenue_since(start_time):
        result = confirmed.filter(booked_at__gte=start_time).aggregate(
            total=Sum('theater__ticket_price')
        )
        return result['total'] or 0

    revenue_today = revenue_since(today_start)
    revenue_week = revenue_since(week_start)
    revenue_month = revenue_since(month_start)
    revenue_year = revenue_since(year_start)

    top_movies = Movie.objects.annotate(
        booking_count=Count('theaters__seats__booking', filter=models.Q(theaters__seats__booking__status='confirmed'))
    ).order_by('-booking_count')[:5]

    top_theaters = Theater.objects.annotate(
        booking_count=Count('seats__booking', filter=models.Q(seats__booking__status='confirmed')),
        revenue=Sum('seats__booking__theater__ticket_price', filter=models.Q(seats__booking__status='confirmed'))
    ).order_by('-booking_count')[:5]

    theater_occupancy = []
    for theater in Theater.objects.all():
        total_seats = theater.seats.count()
        booked_seats = theater.seats.filter(is_booked=True).count()
        occupancy_pct = round((booked_seats / total_seats) * 100, 1) if total_seats else 0
        theater_occupancy.append({
            'theater': theater,
            'total_seats': total_seats,
            'booked_seats': booked_seats,
            'occupancy_pct': occupancy_pct,
        })

    booking_trend = (
        Booking.objects.filter(booked_at__gte=today_start - timedelta(days=6))
        .annotate(day=models.functions.TruncDate('booked_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    peak_hours = (
        Booking.objects.annotate(hour=models.functions.ExtractHour('booked_at'))
        .values('hour')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )

    total_bookings = Booking.objects.count()
    cancelled_count = Booking.objects.filter(status='cancelled').count()
    cancellation_rate = round((cancelled_count / total_bookings) * 100, 1) if total_bookings else 0

    from django.contrib.auth.models import User
    user_growth = (
        User.objects.filter(date_joined__gte=today_start - timedelta(days=6))
        .annotate(day=models.functions.TruncDate('date_joined'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    return render(request, 'movies/admin_dashboard.html', {
        'revenue_today': revenue_today,
        'revenue_week': revenue_week,
        'revenue_month': revenue_month,
        'revenue_year': revenue_year,
        'top_movies': top_movies,
        'top_theaters': top_theaters,
        'theater_occupancy': theater_occupancy,
        'booking_trend': booking_trend,
        'peak_hours': peak_hours,
        'total_bookings': total_bookings,
        'cancelled_count': cancelled_count,
        'cancellation_rate': cancellation_rate,
        'user_growth': user_growth,
        'range_start': range_start,
        'range_end': range_end,
        'range_revenue': range_revenue,
        'range_count': range_count,
    })

HOLD_MINUTES = 2

@staff_member_required
def export_bookings_csv(request):
    range_start = request.GET.get('start_date', '')
    range_end = request.GET.get('end_date', '')

    bookings = Booking.objects.filter(
        status='confirmed'
    ).select_related('user', 'movie', 'theater', 'seat')

    if range_start:
        bookings = bookings.filter(booked_at__date__gte=range_start)
    if range_end:
        bookings = bookings.filter(booked_at__date__lte=range_end)

    response = HttpResponse(content_type='text/csv')
    response['Content-Disposition'] = 'attachment; filename="bookings_report.csv"'

    writer = csv.writer(response)
    writer.writerow(['Booking ID', 'User', 'Movie', 'Theater', 'Seat', 'Ticket Price', 'Booked At'])

    for booking in bookings:
        writer.writerow([
            booking.id,
            booking.user.username,
            booking.movie.name,
            booking.theater.name,
            booking.seat.seat_number,
            booking.theater.ticket_price,
            booking.booked_at.strftime('%Y-%m-%d %H:%M'),
        ])

    return response

def movie_list(request):
    search_query = request.GET.get('search', '')
    selected_genre = request.GET.get('genre', '')
    selected_language = request.GET.get('language', '')
    selected_city = request.GET.get('city', '')
    selected_theater = request.GET.get('theater', '')
    selected_release_date = request.GET.get('release_date', '')
    selected_show_time = request.GET.get('show_time', '')
    sort_by = request.GET.get('sort', '')

    movies = Movie.objects.all()

    if search_query:
        movies = movies.filter(name__icontains=search_query)
    if selected_genre:
        movies = movies.filter(genre=selected_genre)
    if selected_language:
        movies = movies.filter(language=selected_language)
    if selected_city:
        movies = movies.filter(theaters__city=selected_city)
    if selected_theater:
        movies = movies.filter(theaters__name=selected_theater)
    if selected_release_date:
        movies = movies.filter(release_date=selected_release_date)
    if selected_show_time:
        time_ranges = {
            'morning': (6, 12), 'afternoon': (12, 17), 'evening': (17, 21), 'night': (21, 24),
        }
        if selected_show_time in time_ranges:
            start_hour, end_hour = time_ranges[selected_show_time]
            movies = movies.filter(theaters__time__hour__gte=start_hour, theaters__time__hour__lt=end_hour)

    movies = movies.distinct()

    all_genres = Movie.objects.exclude(genre='').values_list('genre', flat=True).distinct()
    all_languages = Movie.objects.exclude(language='').values_list('language', flat=True).distinct()
    all_cities = Theater.objects.exclude(city='').values_list('city', flat=True).distinct()
    all_theaters = Theater.objects.values_list('name', flat=True).distinct()

    if sort_by == 'newest':
        movies = movies.order_by('-release_date')
    elif sort_by == 'rating':
        movies = movies.order_by('-rating')
    elif sort_by == 'price':
        movies = movies.order_by('theaters__ticket_price')
    elif sort_by == 'popularity':
        movies = movies.annotate(booking_count=Count('theaters__seats__booking')).order_by('-booking_count')

    movie_count = movies.count()

    paginator = Paginator(movies, 6)
    page_number = request.GET.get('page', 1)
    page_obj = paginator.get_page(page_number)

    preferred_genres = set()
    if request.user.is_authenticated:
        booked_genres = Booking.objects.filter(user=request.user).values_list('movie__genre', flat=True)
        preferred_genres.update([g for g in booked_genres if g])

    recently_viewed_ids = request.session.get('recently_viewed', [])
    if recently_viewed_ids:
        viewed_genres = Movie.objects.filter(id__in=recently_viewed_ids).exclude(genre='').values_list('genre', flat=True)
        preferred_genres.update(viewed_genres)

    recommended_movies = []
    if preferred_genres:
        recommended_movies = Movie.objects.filter(genre__in=preferred_genres)
        if recently_viewed_ids:
            recommended_movies = recommended_movies.exclude(id__in=recently_viewed_ids)
        recommended_movies = recommended_movies.distinct()[:4]

    if not recommended_movies:
        recommended_movies = Movie.objects.annotate(
            booking_count=Count('theaters__seats__booking')
        ).order_by('-booking_count')[:4]

    return render(request, 'movies/movie_list.html', {
        'movies': page_obj,
        'page_obj': page_obj,
        'movie_count': movie_count,
        'all_genres': all_genres,
        'all_languages': all_languages,
        'all_cities': all_cities,
        'all_theaters': all_theaters,
        'search_query': search_query,
        'selected_genre': selected_genre,
        'selected_language': selected_language,
        'selected_city': selected_city,
        'selected_theater': selected_theater,
        'selected_release_date': selected_release_date,
        'selected_show_time': selected_show_time,
        'sort_by': sort_by,
        'recommended_movies': recommended_movies,
    })

def theater_list(request,movie_id):
    movie = get_object_or_404(Movie,id=movie_id)
    theater=Theater.objects.filter(movie=movie)

    recently_viewed = request.session.get('recently_viewed', [])
    if movie_id in recently_viewed:
        recently_viewed.remove(movie_id)
    recently_viewed.insert(0, movie_id)
    request.session['recently_viewed'] = recently_viewed[:5]
    reviews = movie.reviews.all().order_by('-created_at')
    my_review = None
    can_review = False
    if request.user.is_authenticated:
        my_review = reviews.filter(user=request.user).first()
        can_review = Booking.objects.filter(user=request.user, movie=movie, status='confirmed').exists()

    similar_movies = Movie.objects.exclude(id=movie.id)
    if movie.genre or movie.language:
        similar_movies = similar_movies.filter(
            models.Q(genre=movie.genre) | models.Q(language=movie.language)
        )
    similar_movies = similar_movies.distinct()[:4]

    trending_movies = Movie.objects.exclude(id=movie.id).annotate(
        booking_count=Count('theaters__seats__booking')
    ).order_by('-booking_count')[:4]

    recent_movies = Movie.objects.exclude(id=movie.id).exclude(release_date__isnull=True).order_by('-release_date')[:4]

    return render(request,'movies/theater_list.html',{
        'movie':movie,
        'theaters':theater,
        'reviews': reviews,
        'my_review': my_review,
        'can_review': can_review,
        'similar_movies': similar_movies,
        'trending_movies': trending_movies,
        'recent_movies': recent_movies,
    })

@login_required(login_url='/login/')
def submit_review(request, movie_id):
    movie = get_object_or_404(Movie, id=movie_id)

    has_watched = Booking.objects.filter(user=request.user, movie=movie, status='confirmed').exists()
    if not has_watched:
        messages.error(request, "You can only review a movie after booking and watching it.")
        return redirect('theater_list', movie_id=movie.id)

    existing_review = Review.objects.filter(user=request.user, movie=movie).first()

    if request.method == 'POST':
        rating = request.POST.get('rating')
        comment = request.POST.get('comment', '')

        if existing_review:
            existing_review.rating = rating
            existing_review.comment = comment
            existing_review.save()
            messages.success(request, "Your review has been updated.")
        else:
            Review.objects.create(user=request.user, movie=movie, rating=rating, comment=comment)
            messages.success(request, "Thanks for your review!")

        return redirect('theater_list', movie_id=movie.id)

    return render(request, 'movies/submit_review.html', {
        'movie': movie,
        'existing_review': existing_review,
    })

@login_required(login_url='/login/')
def report_review(request, review_id):
    review = get_object_or_404(Review, id=review_id)
    review.reported_count += 1
    review.save(update_fields=['reported_count'])
    messages.success(request, "Thanks, this review has been reported for moderation.")
    return redirect('theater_list', movie_id=review.movie.id)

def _release_expired_seats(theater):
    """Free up any seat whose 2-minute hold has run out. Called every time seats are viewed."""
    expired = Seat.objects.filter(theater=theater, reserved_until__lte=timezone.now())
    for seat in expired:
        Booking.objects.filter(seat=seat, status='pending').delete()
        seat.reserved_by = None
        seat.reserved_until = None
        seat.save(update_fields=['reserved_by', 'reserved_until'])


@login_required(login_url='/login/')
def book_seats(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    _release_expired_seats(theater)
    seats = Seat.objects.filter(theater=theater)

    if request.method == 'POST':
        selected_seats = request.POST.getlist('seats')
        if not selected_seats:
            return render(request, "movies/seat_selection.html",
                           {'theaters': theater, 'seats': seats, 'error': "No seat selected"})

        error_seats = []
        reserved_seats = []
        hold_until = timezone.now() + timedelta(minutes=HOLD_MINUTES)

        with transaction.atomic():
            for seat_id in selected_seats:
                seat = Seat.objects.select_for_update().get(id=seat_id, theater=theater)
                if seat.is_booked or seat.is_reserved():
                    error_seats.append(seat.seat_number)
                    continue
                seat.reserved_by = request.user
                seat.reserved_until = hold_until
                seat.save(update_fields=['reserved_by', 'reserved_until'])
                Booking.objects.create(
                    user=request.user, seat=seat, movie=theater.movie,
                    theater=theater, status='pending'
                )
                reserved_seats.append(seat)

        if error_seats:
            error_message = f"These seats were just taken by someone else: {', '.join(error_seats)}"
            return render(request, 'movies/seat_selection.html',
                           {'theaters': theater, 'seats': seats, 'error': error_message})

        if not reserved_seats:
            return redirect('book_seats', theater_id=theater.id)

        return redirect('confirm_booking', theater_id=theater.id)

    return render(request, 'movies/seat_selection.html', {'theaters': theater, 'seats': seats})


@login_required(login_url='/login/')
def confirm_booking(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    _release_expired_seats(theater)

    my_pending = Booking.objects.filter(
        theater=theater, user=request.user, status='pending'
    ).select_related('seat')

    if not my_pending.exists():
        messages.error(request, "Your seat hold expired. Please select seats again.")
        return redirect('book_seats', theater_id=theater.id)

    if request.method == 'POST':
        order_id = uuid.uuid4()
        total_amount = my_pending.count() * theater.ticket_price
        my_pending.update(order_id=order_id)

        if settings.RAZORPAY_SANDBOX_MODE:
            # No real Razorpay account yet — simulate an order so the flow can still be tested.
            fake_razorpay_order_id = f'order_SANDBOX_{order_id}'
            Payment.objects.create(
                order_id=order_id,
                user=request.user,
                amount=total_amount,
                razorpay_order_id=fake_razorpay_order_id,
                status='created',
            )
            return render(request, 'movies/sandbox_checkout.html', {
                'order_id': order_id,
                'amount': total_amount,
                'movie_name': theater.movie.name,
            })

        client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))
        razorpay_order = client.order.create({
            'amount': int(total_amount * 100),
            'currency': 'INR',
            'receipt': str(order_id),
        })

        Payment.objects.create(
            order_id=order_id,
            user=request.user,
            amount=total_amount,
            razorpay_order_id=razorpay_order['id'],
            status='created',
        )

        return render(request, 'movies/razorpay_checkout.html', {
            'razorpay_order_id': razorpay_order['id'],
            'razorpay_key_id': settings.RAZORPAY_KEY_ID,
            'amount_paise': int(total_amount * 100),
            'order_id': order_id,
            'user_email': request.user.email,
            'movie_name': theater.movie.name,
        })

    hold_until = min(b.seat.reserved_until for b in my_pending if b.seat.reserved_until)
    seconds_left = max(0, int((hold_until - timezone.now()).total_seconds()))

    return render(request, 'movies/confirm_booking.html', {
        'theater': theater,
        'bookings': my_pending,
        'seconds_left': seconds_left,
    })


@login_required(login_url='/login/')
def download_ticket(request, order_id):
    from .ticket_utils import generate_ticket_pdf

    bookings = list(Booking.objects.filter(
        order_id=order_id, user=request.user, status='confirmed'
    ).select_related('movie', 'theater', 'seat'))

    if not bookings:
        messages.error(request, "Ticket not found.")
        return redirect('profile')

    pdf_bytes = generate_ticket_pdf(bookings)

    response = HttpResponse(pdf_bytes, content_type='application/pdf')
    response['Content-Disposition'] = f'attachment; filename="ticket_{order_id}.pdf"'
    return response


@login_required(login_url='/login/')
def payment_success(request):
    if request.method != 'POST':
        return redirect('movie_list')

    razorpay_payment_id = request.POST.get('razorpay_payment_id')
    razorpay_order_id = request.POST.get('razorpay_order_id')
    razorpay_signature = request.POST.get('razorpay_signature')

    payment = get_object_or_404(Payment, razorpay_order_id=razorpay_order_id, user=request.user)

    client = razorpay.Client(auth=(settings.RAZORPAY_KEY_ID, settings.RAZORPAY_KEY_SECRET))

    try:
        client.utility.verify_payment_signature({
            'razorpay_order_id': razorpay_order_id,
            'razorpay_payment_id': razorpay_payment_id,
            'razorpay_signature': razorpay_signature,
        })
        signature_valid = True
    except razorpay.errors.SignatureVerificationError:
        signature_valid = False

    if not signature_valid:
        payment.status = 'failed'
        payment.save(update_fields=['status'])
        messages.error(request, "Payment verification failed. Please try again.")
        return redirect('payment_failed', order_id=payment.order_id)

    with transaction.atomic():
        payment.razorpay_payment_id = razorpay_payment_id
        payment.razorpay_signature = razorpay_signature
        payment.status = 'success'
        payment.save(update_fields=['razorpay_payment_id', 'razorpay_signature', 'status'])

        bookings = Booking.objects.filter(order_id=payment.order_id, status='pending').select_for_update()
        for booking in bookings:
            booking.status = 'confirmed'
            booking.save(update_fields=['status'])
            seat = booking.seat
            seat.is_booked = True
            seat.reserved_by = None
            seat.reserved_until = None
            seat.save(update_fields=['is_booked', 'reserved_by', 'reserved_until'])

    send_ticket_email.delay(str(payment.order_id))
    messages.success(request, "Payment successful! Your ticket is being emailed to you.")
    return redirect('profile')


@login_required(login_url='/login/')
def payment_failed(request, order_id):
    bookings = Booking.objects.filter(order_id=order_id, user=request.user, status='pending')
    for booking in bookings:
        seat = booking.seat
        seat.reserved_by = None
        seat.reserved_until = None
        seat.save(update_fields=['reserved_by', 'reserved_until'])
    bookings.delete()

    Payment.objects.filter(order_id=order_id, user=request.user).update(status='failed')

    messages.error(request, "Payment was not completed. Your seat hold has been released.")
    return render(request, 'movies/payment_failed.html', {})


@login_required(login_url='/login/')
def simulate_payment(request, order_id):
    """SANDBOX ONLY — lets us test the full booking flow without a real Razorpay account."""
    if not settings.RAZORPAY_SANDBOX_MODE:
        return redirect('movie_list')

    payment = get_object_or_404(Payment, order_id=order_id, user=request.user)
    outcome = request.POST.get('outcome')

    if outcome == 'success':
        with transaction.atomic():
            payment.razorpay_payment_id = f'pay_SANDBOX_{order_id}'
            payment.status = 'success'
            payment.save(update_fields=['razorpay_payment_id', 'status'])

            bookings = Booking.objects.filter(order_id=order_id, status='pending').select_for_update()
            for booking in bookings:
                booking.status = 'confirmed'
                booking.save(update_fields=['status'])
                seat = booking.seat
                seat.is_booked = True
                seat.reserved_by = None
                seat.reserved_until = None
                seat.save(update_fields=['is_booked', 'reserved_by', 'reserved_until'])

        send_ticket_email.delay(str(order_id))
        messages.success(request, "Payment successful! Your ticket is being emailed to you.")
        return redirect('profile')

    return payment_failed(request, order_id)