"""Minimal trusted gateway boundary; browser identity headers alone are worthless."""
import hmac
import os
from fastapi import HTTPException, Request

def verify_service(request: Request) -> None:
    expected = os.getenv('EDUPREDICT_SERVICE_KEY', '').strip()
    if len(expected) < 32:
        raise HTTPException(503, 'Prediction service authentication is not configured')
    supplied = request.headers.get('x-service-key', '')
    if not hmac.compare_digest(supplied.encode('utf-8'), expected.encode('utf-8')):
        raise HTTPException(401, 'Invalid service credential')

def require_student_actor(request: Request) -> None:
    verify_service(request)
    role = request.headers.get('x-edufusion-role', '')
    if role == 'admin':
        return
    claimed = request.headers.get('x-edufusion-student-id', '')
    target = str(request.path_params.get('id_student', ''))
    if (role != 'student' or not claimed.isascii() or not claimed.isdigit()
            or len(claimed) > 16 or not target.isascii() or not target.isdigit()
            or len(target) > 16 or int(claimed) <= 0 or int(claimed) != int(target)):
        raise HTTPException(403, 'Student access is not permitted')

def require_service_admin(request: Request) -> None:
    verify_service(request)
    if request.headers.get('x-edufusion-role') != 'admin':
        raise HTTPException(403, 'Administrative prediction access is required')
