from enum import Enum


class Role(str, Enum):
    owner = "owner"
    manager = "manager"
    head_chef = "head_chef"
    cashier = "cashier"
    waiter = "waiter"
    kitchen = "kitchen"
    warehouse = "warehouse"


# Role yang boleh dikelola manager di outletnya (manager dan head chef hanya oleh owner)
STAFF_ROLES = {Role.cashier, Role.waiter, Role.kitchen, Role.warehouse}
