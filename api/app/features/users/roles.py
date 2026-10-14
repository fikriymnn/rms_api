from enum import Enum


class Role(str, Enum):
    owner = "owner"
    manager = "manager"
    cashier = "cashier"
    waiter = "waiter"
    kitchen = "kitchen"
    warehouse = "warehouse"


STAFF_ROLES = {Role.cashier, Role.waiter, Role.kitchen, Role.warehouse}
