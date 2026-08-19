from django.core.validators import MinValueValidator, MaxValueValidator
from django.db import models
from django.contrib.auth.models import User 
from django.utils import timezone


class Movie(models.Model):
    name = models.CharField(max_length=255)
    image = models.ImageField(upload_to="movies/")
    rating = models.DecimalField(max_digits=3, decimal_places=1)
    cast = models.TextField()
    description = models.TextField(blank=True, null=True)
    genre = models.CharField(max_length=100, blank=True, default='')
    language = models.CharField(max_length=50, blank=True, default='')
    release_date = models.DateField(null=True, blank=True)

    trailer_url = models.URLField(blank=True, default='', help_text="Paste a YouTube video link")
    duration_minutes = models.PositiveIntegerField(null=True, blank=True, help_text="Movie length in minutes")

    AGE_RATING_CHOICES = [
        ('U', 'U - Universal'),
        ('UA', 'UA - Parental Guidance'),
        ('A', 'A - Adults Only'),
        ('S', 'S - Restricted to Special Class'),
    ]
    age_certification = models.CharField(max_length=2, choices=AGE_RATING_CHOICES, blank=True, default='')

    def average_rating(self):
        """Calculated from actual user reviews, not the fixed 'rating' field."""
        result = self.reviews.aggregate(avg=models.Avg('rating'))
        return round(result['avg'], 1) if result['avg'] else None

    def __str__(self):
        return self.name


    def __str__(self):
        return self.name

class MoviePoster(models.Model):
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='posters')
    image = models.ImageField(upload_to="movies/posters/")

    def __str__(self):
        return f'Poster for {self.movie.name}'

    

class Theater(models.Model):
    name = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE,related_name='theaters')
    time= models.DateTimeField()
    city = models.CharField(max_length=100, blank=True, default='')
    ticket_price = models.DecimalField(max_digits=6, decimal_places=2, default=200.00)

    def __str__(self):
        return f'{self.name} - {self.movie.name} at {self.time}'

class Seat(models.Model):
    theater = models.ForeignKey(Theater,on_delete=models.CASCADE,related_name='seats')
    seat_number = models.CharField(max_length=10)
    is_booked=models.BooleanField(default=False)
    reserved_by = models.ForeignKey(User, on_delete=models.SET_NULL, null=True, blank=True, related_name='reserved_seats')
    reserved_until = models.DateTimeField(null=True, blank=True)


    def is_reserved(self):
        """True only while someone's 2-minute hold is still active."""
        return self.reserved_until is not None and self.reserved_until > timezone.now()

    def release_if_expired(self):
        """If the hold time has passed, free the seat back up."""
        if self.reserved_until is not None and self.reserved_until <= timezone.now():
            self.reserved_by = None
            self.reserved_until = None
            self.save(update_fields=['reserved_by', 'reserved_until'])
            return True
        return False

    def status(self):
        """Tells the webpage: is this seat available, on-hold, or booked?"""
        if self.is_booked:
            return 'booked'
        if self.is_reserved():
            return 'reserved'
        return 'available'

    def __str__(self):
        return f'{self.seat_number} in {self.theater.name}'
    

class Booking(models.Model):
    STATUS_CHOICES = [
        ('pending', 'Pending Payment'),
        ('confirmed', 'Confirmed'),
        ('cancelled', 'Cancelled'),
    ]
    user=models.ForeignKey(User,on_delete=models.CASCADE)
    seat=models.OneToOneField(Seat,on_delete=models.CASCADE)
    movie=models.ForeignKey(Movie,on_delete=models.CASCADE)
    theater=models.ForeignKey(Theater,on_delete=models.CASCADE)
    booked_at=models.DateTimeField(auto_now_add=True)
    status=models.CharField(max_length=10, choices=STATUS_CHOICES, default='pending')
    
    def __str__(self):
        return f'Booking by{self.user.username} for {self.seat.seat_number} at {self.theater.name}'

from django.core.validators import MinValueValidator, MaxValueValidator

class Review(models.Model):
    user = models.ForeignKey(User, on_delete=models.CASCADE, related_name='reviews')
    movie = models.ForeignKey(Movie, on_delete=models.CASCADE, related_name='reviews')
    rating = models.PositiveSmallIntegerField(validators=[MinValueValidator(1), MaxValueValidator(5)])
    comment = models.TextField(blank=True)
    created_at = models.DateTimeField(auto_now_add=True)
    updated_at = models.DateTimeField(auto_now=True)
    reported_count = models.PositiveIntegerField(default=0)

    class Meta:
        unique_together = ('user', 'movie')

    def is_verified_viewer(self):
        """True if this reviewer actually had a confirmed booking for this movie."""
        return Booking.objects.filter(user=self.user, movie=self.movie, status='confirmed').exists()

    def __str__(self):
        return f'{self.user.username} rated {self.movie.name}: {self.rating}/5'