import random

def generate_random_number():
    return random.randint(1, 5)

def generate_two_unique_numbers():
    return random.sample(range(1, 6), 2)

# Example usage
print("Single random number:", generate_random_number())
print("Two unique random numbers:", generate_two_unique_numbers())
