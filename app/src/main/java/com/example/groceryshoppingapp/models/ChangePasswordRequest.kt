package com.example.groceryshoppingapp.models

data class ChangePasswordRequest(
    val username: String,
    val old_password: String,
    val new_password: String
)
