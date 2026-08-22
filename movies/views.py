from django.contrib.admin.views.decorators import staff_member_required
from django.shortcuts import render, redirect ,get_object_or_404
from .models import Movie,Theater,Seat,Booking,Review
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

    # custom date range filter
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

    # Occupancy % per theater: booked seats / total seats
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

        # Booking trends: bookings per day, last 7 days
        # Booking trends: bookings per day, last 7 days
    booking_trend = (
        Booking.objects.filter(booked_at__gte=today_start - timedelta(days=6))
        .annotate(day=models.functions.TruncDate('booked_at'))
        .values('day')
        .annotate(count=Count('id'))
        .order_by('day')
    )

    # Peak booking hours: which hour of the day gets the most bookings
    peak_hours = (
        Booking.objects.annotate(hour=models.functions.ExtractHour('booked_at'))
        .values('hour')
        .annotate(count=Count('id'))
        .order_by('-count')[:5]
    )

    # Cancellation stats
    total_bookings = Booking.objects.count()
    cancelled_count = Booking.objects.filter(status='cancelled').count()
    cancellation_rate = round((cancelled_count / total_bookings) * 100, 1) if total_bookings else 0

    # User growth: new signups per day, last 7 days
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

HOLD_MINUTES = 2  # how long a seat stays "reserved" before it's auto-released

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
            'morning': (6, 12),
            'afternoon': (12, 17),
            'evening': (17, 21),
            'night': (21, 24),
        }
        if selected_show_time in time_ranges:
            start_hour, end_hour = time_ranges[selected_show_time]
            movies = movies.filter(theaters__time__hour__gte=start_hour, theaters__time__hour__lt=end_hour)

    # filtering "through" theaters can create duplicate rows, so remove duplicates
    movies = movies.distinct()

    # dropdown option lists
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

    # ---- Recommended for You ----
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
        # fallback for new users with no history yet: show trending movies
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

    # remember this movie was viewed, for the "Recommended for You" feature
    recently_viewed = request.session.get('recently_viewed', [])
    if movie_id in recently_viewed:
        recently_viewed.remove(movie_id)
    recently_viewed.insert(0, movie_id)
    request.session['recently_viewed'] = recently_viewed[:5]  # keep only the last 5
    reviews = movie.reviews.all().order_by('-created_at')
    my_review = None
    can_review = False
    if request.user.is_authenticated:
        my_review = reviews.filter(user=request.user).first()
        can_review = Booking.objects.filter(user=request.user, movie=movie, status='confirmed').exists()

    # Similar movies: same genre OR same language, excluding this movie itself
    similar_movies = Movie.objects.exclude(id=movie.id)
    if movie.genre or movie.language:
        similar_movies = similar_movies.filter(
            models.Q(genre=movie.genre) | models.Q(language=movie.language)
        )
    similar_movies = similar_movies.distinct()[:4]

    # Trending: most-booked movies overall, excluding this one
    trending_movies = Movie.objects.exclude(id=movie.id).annotate(
        booking_count=Count('theaters__seats__booking')
    ).order_by('-booking_count')[:4]

    # Recently released: newest release dates, excluding this one
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
        # also clean up the pending Booking row that was holding this seat
        Booking.objects.filter(seat=seat, status='pending').delete()
        seat.reserved_by = None
        seat.reserved_until = None
        seat.save(update_fields=['reserved_by', 'reserved_until'])


@login_required(login_url='/login/')
def book_seats(request, theater_id):
    theater = get_object_or_404(Theater, id=theater_id)
    _release_expired_seats(theater)  # clean up any stale holds before showing the page
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

        # send them to the confirm/payment page with their 2-minute countdown
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
        with transaction.atomic():
            for booking in my_pending.select_for_update():
                booking.status = 'confirmed'
                booking.save(update_fields=['status'])
                seat = booking.seat
                seat.is_booked = True
                seat.reserved_by = None
                seat.reserved_until = None
                seat.save(update_fields=['is_booked', 'reserved_by', 'reserved_until'])
        messages.success(request, "Booking confirmed!")
        return redirect('profile')

    hold_until = min(b.seat.reserved_until for b in my_pending if b.seat.reserved_until)
    seconds_left = max(0, int((hold_until - timezone.now()).total_seconds()))

    return render(request, 'movies/confirm_booking.html', {
        'theater': theater,
        'bookings': my_pending,
        'seconds_left': seconds_left,
    })