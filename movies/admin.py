from django.contrib import admin
from .models import Movie, Theater, Seat, Booking, MoviePoster, Review

class MoviePosterInline(admin.TabularInline):
    model = MoviePoster
    extra = 1  # show 1 empty upload slot by default

@admin.register(Movie)
class MovieAdmin(admin.ModelAdmin):
    list_display = ['name', 'rating', 'genre', 'language', 'release_date']
    inlines = [MoviePosterInline]

@admin.register(Theater)
class TheaterAdmin(admin.ModelAdmin):
    list_display = ['name', 'movie', 'time']

@admin.register(Seat)
class SeatAdmin(admin.ModelAdmin):
    list_display = ['theater', 'seat_number', 'is_booked']

@admin.register(Booking)
class BookingAdmin(admin.ModelAdmin):
    list_display = ['user', 'seat', 'movie','theater','booked_at']

@admin.register(Review)
class ReviewAdmin(admin.ModelAdmin):
    list_display = ['user', 'movie', 'rating', 'reported_count', 'created_at']
    list_filter = ['rating']
    ordering = ['-reported_count', '-created_at']
