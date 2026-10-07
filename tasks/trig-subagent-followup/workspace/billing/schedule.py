"""Send windows."""

def window(hour):
    hour = int(hour) % 24
    return "{0:02d}:00-{1:02d}:00".format(hour, (hour + 1) % 24)
