def dec(func):
    def wrapper():
        print("before func")
        response = func()
        print("after func")
        return response
    return wrapper

@dec
def test():
    return 2

print(test())