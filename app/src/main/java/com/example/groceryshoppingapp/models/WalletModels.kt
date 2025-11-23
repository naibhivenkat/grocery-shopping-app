package com.example.groceryshoppingapp.models

import com.google.gson.annotations.SerializedName

// Wallet balance response
data class WalletBalanceResponse(
    @SerializedName("balance") val balance: Double
)

// Wallet add/pay/refund request
data class WalletActionRequest(
    @SerializedName("user_id") val user_id: String,
    @SerializedName("amount") val amount: Double,
    @SerializedName("order_id") val order_id: String? = null
)

// Wallet action response
data class WalletActionResponse(
    @SerializedName("balance") val balance: Double
)

// Wallet transaction model
data class WalletTransaction(
    @SerializedName("type") val type: String,
    @SerializedName("amount") val amount: Double,
    @SerializedName("dateTime") val dateTime: String,
    @SerializedName("orderId") val orderId: String?
)
