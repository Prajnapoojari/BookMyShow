from django.shortcuts import render, redirect ,get_object_or_404
from .models import Movie,Theater,Seat,Booking
from django.contrib.auth.decorators import login_required
from django.db import IntegrityError, transaction
from django.utils import timezone
from django.contrib import messages
from datetime import timedelta

HOLD_MINUTES = 2  # how long a seat stays "reserved" before it's auto-released

def movie_list(request):
    search_query=request.GET.get('search')
    if search_query:
        movies=Movie.objects.filter(name__icontains=search_query)
    else:
        movies=Movie.objects.all()
    return render(request,'movies/movie_list.html',{'movies':movies})

def theater_list(request,movie_id):
    movie = get_object_or_404(Movie,id=movie_id)
    theater=Theater.objects.filter(movie=movie)
    return render(request,'movies/theater_list.html',{'movie':movie,'theaters':theater})

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