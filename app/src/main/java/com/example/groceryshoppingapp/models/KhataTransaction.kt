package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

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

    // ⭐ ALWAYS store timestamp as Long (safe with Parcelize)
    @SerializedName("created_at", alternate = ["createdAt", "timestamp"])
    val createdAt: Long? = null

) : Parcelable {

    // ⭐ Return safe timestamp
    fun getCreatedTimestamp(): Long {
        return createdAt ?: System.currentTimeMillis()
    }
}

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
