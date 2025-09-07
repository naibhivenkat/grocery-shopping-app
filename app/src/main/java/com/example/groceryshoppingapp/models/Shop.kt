package com.example.groceryshoppingapp.models

data class Shop(
    val id: String,
    val name: String,
    val address: String? = null,
    val contact: String,
    val shopkeeper_id: String? = null
)
