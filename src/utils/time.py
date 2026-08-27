from datetime import datetime, timezone


def from_timestamp(ts):
    return (
        datetime.fromtimestamp(ts, tz=timezone.utc)
        .astimezone()
        .strftime("%Y-%m-%d %H:%M:%S") # Adjust to preference
    )