from django.core.exceptions import ValidationError
from django.db import IntegrityError, transaction
from django.db.models import Q
from django.shortcuts import get_object_or_404
from django.utils import timezone
from django.core.mail import send_mail
from django.conf import settings



from rest_framework import status
from rest_framework.authentication import TokenAuthentication
from rest_framework.permissions import IsAuthenticated, AllowAny
from rest_framework.response import Response
from rest_framework.views import APIView
from rest_framework.decorators import api_view, permission_classes

from datetime import datetime, timedelta
from datetime import date

from users.models import Patient
from doctors.models import Kinesiologist
from .models import Appointment, Availability
from .serializers import (
    AppointmentSerializer,
    AvailabilitySerializer,
    KinesiologistSummarySerializer,
    TimeSlotSerializer,
)

SLOT_MINUTES = 45


class AvailabilityListCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request, kinesiologist_id: int):
        kinesiologist = get_object_or_404(
            Kinesiologist.objects.select_related("user"),
            pk=kinesiologist_id
        )

        availability_qs = (
            Availability.objects
            .filter(kinesiologist=kinesiologist)
            .order_by("day", "start_time")
        )

        appointments_qs = (
            Appointment.objects
            .filter(kinesiologist=kinesiologist)
            .select_related("patient_name__user", "kinesiologist__user")
            .order_by("date", "start_time")
        )

        return Response(
            {
                "kinesiologist": KinesiologistSummarySerializer(kinesiologist).data,
                "availability": AvailabilitySerializer(availability_qs, many=True).data,
                "appointments": AppointmentSerializer(appointments_qs, many=True).data,
            },
            status=status.HTTP_200_OK,
        )

    def post(self, request, kinesiologist_id: int):
        kinesiologist = get_object_or_404(
            Kinesiologist.objects.select_related("user"),
            pk=kinesiologist_id
        )

        if not (request.user.is_superuser or request.user == kinesiologist.user):
            return Response(
                {"status": False, "message": "No tiene permisos para registrar este horario."},
                status=status.HTTP_403_FORBIDDEN,
            )

        
        bulk = request.data.get("availability") if isinstance(request.data, dict) else None
        if isinstance(bulk, dict):
            day_map = {
                "mon": 0, "tue": 1, "wed": 2,
                "thu": 3, "fri": 4, "sat": 5, "sun": 6
            }

            created = []
            try:
                with transaction.atomic():
                   
                    Availability.objects.filter(kinesiologist=kinesiologist).delete()

                    for day_key, blocks in bulk.items():
                        if day_key not in day_map:
                            raise ValidationError(f"Día inválido: {day_key}")

                        if not blocks:
                            continue

                        for b in blocks:
                            start = (b.get("start") or b.get("start_time") or "").strip()
                            end = (b.get("end") or b.get("end_time") or "").strip()

                            serializer = AvailabilitySerializer(
                                data={
                                    "day": day_map[day_key],
                                    "start_time": start,
                                    "end_time": end,
                                },
                                context={"kinesiologist": kinesiologist},
                            )
                            serializer.is_valid(raise_exception=True)
                            created.append(serializer.save(kinesiologist=kinesiologist))

            except ValidationError as exc:
                msg = getattr(exc, "messages", [str(exc)])[0]
                return Response(
                    {"status": False, "message": msg},
                    status=status.HTTP_400_BAD_REQUEST,
                )

            except IntegrityError:
                return Response(
                    {
                        "status": False,
                        "message": "No fue posible guardar el horario. Intente nuevamente.",
                    },
                    status=status.HTTP_500_INTERNAL_SERVER_ERROR,
                )

            return Response(
                {
                    "status": True,
                    "message": "Disponibilidad guardada correctamente.",
                    "availability": AvailabilitySerializer(created, many=True).data,
                },
                status=status.HTTP_201_CREATED,
            )

      
        serializer = AvailabilitySerializer(
            data=request.data,
            context={"kinesiologist": kinesiologist},
        )
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                availability = serializer.save(kinesiologist=kinesiologist)
        except ValidationError as exc:
            msg = getattr(exc, "messages", [str(exc)])[0]
            return Response(
                {"status": False, "message": msg},
                status=status.HTTP_400_BAD_REQUEST,
            )
        except IntegrityError:
            return Response(
                {
                    "status": False,
                    "message": "No fue posible guardar el horario. Intente nuevamente.",
                },
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )

        return Response(
            {
                "status": True,
                "message": "Horario registrado correctamente.",
                "availability": AvailabilitySerializer(availability).data,
            },
            status=status.HTTP_201_CREATED,
        )

class AppointmentCreateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def post(self, request, kinesiologist_id: int):
        kinesiologist = get_object_or_404(
            Kinesiologist.objects.select_related("user"),
            pk=kinesiologist_id
        )

        try:
            patient = Patient.objects.select_related("user").get(user=request.user)
        except Patient.DoesNotExist:
            return Response(
                {"status": False, "message": "El usuario no es un paciente válido."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        serializer = AppointmentSerializer(data=request.data)
        serializer.is_valid(raise_exception=True)

        try:
            with transaction.atomic():
                appointment = Appointment.objects.create(
                    kinesiologist=kinesiologist,
                    patient_name=patient,
                    date=serializer.validated_data["date"],
                    start_time=serializer.validated_data["start_time"],
                    end_time=serializer.validated_data["end_time"],
                )
        except IntegrityError:
            return Response(
                {"status": False, "message": "No se pudo crear la cita."},
                status=status.HTTP_500_INTERNAL_SERVER_ERROR,
            )


        send_mail(
            subject="📅 Nueva solicitud de cita",
            message=(
                f"Hola {kinesiologist.user.get_full_name()},\n\n"
                f"El paciente {patient.user.get_full_name()} ha solicitado una cita.\n\n"
                f"📅 Fecha: {appointment.date}\n"
                f"⏰ Hora: {appointment.start_time} - {appointment.end_time}\n\n"
                f"Por favor ingresa al panel para confirmar o rechazar la cita."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[kinesiologist.user.email],
            fail_silently=False,
        )

        return Response(
            {
                "status": True,
                "message": "Hora médica reservada correctamente.",
                "appointment": AppointmentSerializer(appointment).data,
            },
            status=status.HTTP_201_CREATED,
        )




class KinesiologistAvailableSlotsView(APIView):
    """
    Devuelve los horarios disponibles de un kinesiólogo para una fecha dada.
    GET /api/kinesiologists/<kinesiologist_id>/slots/?date=YYYY-MM-DD
    """
    permission_classes = [AllowAny]
    authentication_classes = []

    def get(self, request, kinesiologist_id):
        date_str = request.query_params.get("date")
        if not date_str:
            return Response(
                {"detail": "Parámetro 'date' es obligatorio (YYYY-MM-DD)."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        try:
            target_date = datetime.strptime(date_str, "%Y-%m-%d").date()
        except ValueError:
            return Response(
                {"detail": "Formato de fecha inválido. Usa YYYY-MM-DD."},
                status=status.HTTP_400_BAD_REQUEST,
            )

        day_of_week = target_date.weekday()

        availability_qs = Availability.objects.filter(
            kinesiologist_id=kinesiologist_id,
            day=day_of_week,
        )

        if not availability_qs.exists():
            return Response([], status=status.HTTP_200_OK)

        existing_appointments = Appointment.objects.filter(
            kinesiologist_id=kinesiologist_id,
            date=target_date,
        )

        slot_length = timedelta(minutes=SLOT_MINUTES)
        slots = []

        for avail in availability_qs:
            current_start = datetime.combine(target_date, avail.start_time)
            avail_end_dt = datetime.combine(target_date, avail.end_time)

            while current_start + slot_length <= avail_end_dt:
                current_end = current_start + slot_length

                overlap = existing_appointments.filter(
                    start_time__lt=current_end.time(),
                    end_time__gt=current_start.time(),
                ).exists()

              
                if not overlap:
                    slots.append(
                        {
                            "date": target_date,
                            "start_time": current_start.time(),
                            "end_time": current_end.time(),
                            "datetime": current_start,
                        }
                    )

                current_start += slot_length

        serializer = TimeSlotSerializer(slots, many=True)
        return Response(serializer.data, status=status.HTTP_200_OK)



class KinesiologistUpcomingAppointmentsView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def get(self, request):
        kine = Kinesiologist.objects.filter(user=request.user).first()
        if not kine:
            return Response(
                {"status": False, "message": "El usuario no corresponde a un kinesiólogo."},
                status=status.HTTP_403_FORBIDDEN
            )

        today = timezone.localdate()
        now_time = timezone.localtime().time()

        qs = Appointment.objects.filter(
            kinesiologist=kine
        ).filter(
            Q(date__gt=today) | Q(date=today, start_time__gte=now_time)
        ).select_related("patient_name__user").order_by("date", "start_time")

        data = []
        for a in qs:
            patient_full_name = ""
            if hasattr(a.patient_name, "user") and a.patient_name.user:
                first = getattr(a.patient_name.user, "first_name", "") or ""
                last = getattr(a.patient_name.user, "last_name", "") or ""
                patient_full_name = (first + " " + last).strip()

            data.append({
                "appointment_id": a.id,
                "patient_id": a.patient_name.id,
                "patient_name": patient_full_name if patient_full_name else str(a.patient_name),
                "date": a.date.strftime("%Y-%m-%d"),
                "start_time": a.start_time.strftime("%H:%M"),
                "end_time": a.end_time.strftime("%H:%M"),
                "status": a.status,
                "status_label": a.get_status_display(),
            })

        return Response({"status": True, "appointments": data}, status=status.HTTP_200_OK)



class AppointmentStatusView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, appointment_id):
        appointment = get_object_or_404(
            Appointment.objects.select_related(
                "kinesiologist__user",
                "patient_name__user"
            ),
            id=appointment_id
        )

        if request.user != appointment.kinesiologist.user:
            return Response(
                {"status": False, "message": "No autorizado"},
                status=status.HTTP_403_FORBIDDEN
            )

        new_status = request.data.get("status")
        if new_status not in ["confirmed", "cancelled"]:
            return Response(
                {"status": False, "message": "Estado inválido"},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.status = new_status
        appointment.save(update_fields=["status"])

        patient_user = appointment.patient_name.user
        kine_user = appointment.kinesiologist.user

        status_label = "CONFIRMADA ✅" if new_status == "confirmed" else "CANCELADA ❌"

        send_mail(
            subject=f"📅 Tu cita ha sido {status_label}",
            message=(
                f"Hola {patient_user.get_full_name()},\n\n"
                f"Tu cita con {kine_user.get_full_name()} ha sido {status_label}.\n\n"
                f"📅 Fecha: {appointment.date}\n"
                f"⏰ Hora: {appointment.start_time} - {appointment.end_time}\n\n"
                f"Gracias por usar Centro de Salud y Bienestar."
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[patient_user.email],
            fail_silently=False,
        )

        return Response(
            {
                "status": True,
                "message": f"Cita {appointment.get_status_display()}",
            },
            status=status.HTTP_200_OK
        )







class AppointmentCommentView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, appointment_id):
        appointment = get_object_or_404(Appointment.objects.select_related("kinesiologist__user"), id=appointment_id)

        if request.user != appointment.kinesiologist.user:
            return Response(
                {"status": False, "message": "No autorizado"},
                status=status.HTTP_403_FORBIDDEN
            )

        comment = request.data.get("kine_comment")
        if not comment or not str(comment).strip():
            return Response(
                {"status": False, "message": "El comentario es obligatorio."},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.kine_comment = str(comment).strip()
        appointment.status = "completed"
        appointment.comment_updated_at = timezone.now()
        appointment.save(update_fields=["kine_comment", "status", "comment_updated_at"])

        return Response(
            {"status": True, "message": "Sesión marcada como realizada y comentario guardado."},
            status=status.HTTP_200_OK
        )


@api_view(["GET"])
@permission_classes([IsAuthenticated])
def patient_appointments_history(request):
    qs = (
        Appointment.objects
        .filter(patient_name__user=request.user)
        .select_related("kinesiologist__user")
        .order_by("-date", "-start_time")
    )

    data = []
    for a in qs:
        data.append({
            "id": a.id,
            "date": a.date.strftime("%Y-%m-%d"),
            "time": a.start_time.strftime("%H:%M"),
            "treatment": "Sesión de kinesiología",
            "kinesiologist": a.kinesiologist.user.get_full_name() or a.kinesiologist.user.username,
            "status": a.status,
            "status_label": a.get_status_display(),
            "kine_comment": a.kine_comment or "",
            "comment_updated_at": a.comment_updated_at,
        })

    return Response(data, status=200)


def notify_kinesiologist(appointment):
    kine = appointment.kinesiologist.user
    patient = appointment.patient.user

    send_mail(
        subject="Nueva solicitud de hora",
        message=(
            f"Nuevo paciente solicita una hora:\n\n"
            f"Paciente: {patient.get_full_name()}\n"
            f"Email: {patient.email}\n"
            f"Teléfono: {patient.phone_number}\n\n"
            f"Fecha: {appointment.date}\n"
            f"Hora: {appointment.start_time} - {appointment.end_time}"
        ),
        from_email=settings.DEFAULT_FROM_EMAIL,
        recipient_list=[kine.email],
        fail_silently=False,
    )


class AppointmentStatusUpdateView(APIView):
    authentication_classes = [TokenAuthentication]
    permission_classes = [IsAuthenticated]

    def patch(self, request, appointment_id: int):
        appointment = get_object_or_404(Appointment, pk=appointment_id)

 
        try:
            kine = Kinesiologist.objects.get(user=request.user)
        except Kinesiologist.DoesNotExist:
            return Response(
                {"status": False, "message": "Solo el kinesiólogo puede modificar el estado."},
                status=status.HTTP_403_FORBIDDEN
            )

        if appointment.kinesiologist_id != kine.id:
            return Response(
                {"status": False, "message": "No puedes modificar citas de otro kinesiólogo."},
                status=status.HTTP_403_FORBIDDEN
            )

        new_status = request.data.get("status")
        allowed = ["confirmed", "cancelled", "rejected", "completed", "pending"]

        if new_status not in allowed:
            return Response(
                {"status": False, "message": f"Estado inválido. Usa: {allowed}"},
                status=status.HTTP_400_BAD_REQUEST
            )

        appointment.status = new_status
        appointment.save()

       
        patient_email = appointment.patient_name.user.email
        patient_name = appointment.patient_name.user.get_full_name() or patient_email
        kine_name = appointment.kinesiologist.user.get_full_name() or "Kinesiólogo"

        
        if new_status == "confirmed":
            status_txt = "✅ CONFIRMADA"
            extra = "Tu hora médica fue confirmada."
        elif new_status in ["cancelled", "rejected"]:
            status_txt = "❌ RECHAZADA / CANCELADA"
            extra = "Tu hora médica fue rechazada/cancelada. Puedes agendar otra hora."
        elif new_status == "completed":
            status_txt = "✅ FINALIZADA"
            extra = "Tu sesión fue marcada como realizada."
        else:
            status_txt = f"Estado actualizado: {new_status}"
            extra = "Se actualizó el estado de tu hora."

        comment_line = ""
        if getattr(appointment, "kine_comment", None):
            comment_line = f"\n\n📝 Comentario del kinesiólogo:\n{appointment.kine_comment}"

        send_mail(
            subject=f"Estado de tu hora médica: {status_txt}",
            message=(
                f"Hola {patient_name},\n\n"
                f"{extra}\n\n"
                f"Kinesiólogo: {kine_name}\n"
                f"Fecha: {appointment.date}\n"
                f"Hora: {str(appointment.start_time)[:5]} - {str(appointment.end_time)[:5]}\n"
                f"Estado: {appointment.status}\n"
                f"{comment_line}\n\n"
                f"Centro de Salud y Bienestar"
            ),
            from_email=settings.DEFAULT_FROM_EMAIL,
            recipient_list=[patient_email],
            fail_silently=False,
        )

        return Response(
            {"status": True, "message": "Estado actualizado y correo enviado al paciente."},
            status=status.HTTP_200_OK
        )
