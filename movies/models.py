from django.db import models
from django.contrib.auth.models import User 
from django.utils import timezone


class Movie(models.Model):
    name= models.CharField(max_length=255)
    image= models.ImageField(upload_to="movies/")
    rating = models.DecimalField(max_digits=3,decimal_places=1)
    cast= models.TextField()
    description= models.TextField(blank=True,null=True) # optional

    def __str__(self):
        return self.name

class Theater(models.Model):
    name = models.CharField(max_length=255)
    movie = models.ForeignKey(Movie,on_delete=models.CASCADE,related_name='theaters')
    time= models.DateTimeField()

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