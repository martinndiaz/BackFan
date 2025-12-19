from django.urls import path
from .views import (
    AppointmentCreateView,
    AppointmentStatusUpdateView,
    AvailabilityListCreateView,
    KinesiologistAvailableSlotsView,
    patient_appointments_history,
    KinesiologistUpcomingAppointmentsView,
    AppointmentStatusView,
    AppointmentCommentView,
)

app_name = "scheduling"

urlpatterns = [
    
    path(
        'kinesiologists/<int:kinesiologist_id>/availability/',
        AvailabilityListCreateView.as_view(),
        name='kinesiologist-availability',
    ),

    
    path(
        'kinesiologists/<int:kinesiologist_id>/appointments/',
        AppointmentCreateView.as_view(),
        name='kinesiologist-appointments',
    ),

   
    path(
        'kinesiologists/<int:kinesiologist_id>/slots/',
        KinesiologistAvailableSlotsView.as_view(),
        name='kinesiologist-slots',
    ),

    
    path(
        "patients/appointments/history/",
        patient_appointments_history,
        name="patient-history",
    ),

    
    path(
        "kinesiologist/appointments/upcoming/",
        KinesiologistUpcomingAppointmentsView.as_view(),
        name="kinesiologist-upcoming",
    ),

   
    path(
        "appointments/<int:appointment_id>/status/",
        AppointmentStatusView.as_view(),
        name="appointment-status",
    ),

    
    path(
        "appointments/<int:appointment_id>/comment/",
        AppointmentCommentView.as_view(),
        name="appointment-comment",
    ),

    path(
    "api/kinesiologists/<int:kinesiologist_id>/appointments/",
    AppointmentCreateView.as_view(),
    name="create-appointment",
    ),

    path("api/appointments/<int:appointment_id>/status/",  
    AppointmentStatusUpdateView.as_view(), 
    name="appointment-status"
    ),



]
