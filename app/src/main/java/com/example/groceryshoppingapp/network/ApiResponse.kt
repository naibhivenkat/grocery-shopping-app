package com.example.groceryshoppingapp.network

data class ApiResponse(
    val success: Boolean,
    val message: String? = null,
    val invoiceUrl: String? = null
)
