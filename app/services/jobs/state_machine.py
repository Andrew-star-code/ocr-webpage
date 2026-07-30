from app.core.exceptions import ServiceError
TERMINAL={"completed","completed_with_warnings","failed","cancelled"}
TRANSITIONS={
 "queued":{"validating","cancelled"},"validating":{"rendering","failed","cancelled"},
 "rendering":{"preprocessing","recognizing","failed","cancelled"},"preprocessing":{"recognizing","failed","cancelled"},
 "recognizing":{"assembling","exporting","failed","cancelled"},"assembling":{"exporting","failed","cancelled"},
 "exporting":{"completed","completed_with_warnings","failed","cancelled"},
}
class JobStateConflict(ServiceError):
 def __init__(self,message="Job state changed concurrently"):super().__init__("job_state_conflict",message,409)
def validate_transition(current,target):
 if current in TERMINAL:raise JobStateConflict("Terminal job cannot be updated")
 if target==current:return
 if target not in TRANSITIONS.get(current,set()):raise JobStateConflict(f"Invalid transition {current} -> {target}")
