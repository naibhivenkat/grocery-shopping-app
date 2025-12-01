package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.firebase.firestore.IgnoreExtraProperties
import com.google.gson.annotations.SerializedName
import kotlinx.parcelize.Parcelize

@IgnoreExtraProperties
@Parcelize
data class KhataTransaction(
    @SerializedName("tx_id") var txId: String? = null,
    @SerializedName("type") var type: String? = null,          // "debit" / "credit"
    @SerializedName("amount") var amount: Double? = 0.0,
    @SerializedName("note") var note: String? = null,
    @SerializedName("order_id") var orderId: String? = null,
    @SerializedName("created_at") var createdAt: String? = null
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
