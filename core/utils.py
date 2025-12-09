import locale

def format_inr(amount, decimals=2):
    """
    Format a number as INR currency (e.g., 1,00,000.00).
    """
    if amount is None:
        return ""
    
    try:
        # Convert to string with specified decimal places
        s = "{:.{}f}".format(amount, decimals)
        if decimals > 0:
            parts = s.split('.')
            integer_part = parts[0]
            decimal_part = parts[1]
        else:
            integer_part = s
            decimal_part = ""
        
        # Handle the last 3 digits of integer part
        last_three = integer_part[-3:]
        rest = integer_part[:-3]
        
        if rest:
            # Add commas to the rest (every 2 digits)
            rest_formatted = ""
            for i, digit in enumerate(reversed(rest)):
                if i > 0 and i % 2 == 0:
                    rest_formatted = "," + rest_formatted
                rest_formatted = digit + rest_formatted
            
            result = rest_formatted + "," + last_three
        else:
            result = last_three
            
        if decimals > 0:
            return result + "." + decimal_part
        else:
            return result
    except Exception:
        return str(amount)
