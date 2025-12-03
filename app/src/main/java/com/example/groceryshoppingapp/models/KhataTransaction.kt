package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.firebase.firestore.IgnoreExtraProperties
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize
import com.google.firebase.firestore.PropertyName


@IgnoreExtraProperties
@Parcelize
data class KhataTransaction(

    @SerializedName("tx_id")
    val txId: String? = null,

    @SerializedName("shop_id")
    val shopId: String? = null,

    @SerializedName("customer_id")
    val customerId: String? = null,

    @SerializedName("type")
    val type: String? = null,

    @SerializedName("amount")
    val amount: Double? = null,

    @SerializedName("note")
    val note: String? = null,

    @SerializedName("order_id")
    val orderId: String? = null,

    // ⭐ THIS IS THE ONLY IMPORTANT FIX:
    @SerializedName("created_at")
    val createdAt: String? = null

) : Parcelable

data class KhataLedgerResponse(
    val success: Boolean,
    val account: KhataAccount?,
    val transactions: List<KhataTransaction>?
)

data class KhataTransactionRequest(
    val shop_id: String,
    val customer_id: String,
    val type: String,
    val amount: Double,
    val note: String
)
