package com.example.groceryshoppingapp.models

import android.os.Parcelable
import com.google.gson.annotations.SerializedName
import com.google.firebase.firestore.PropertyName
import kotlinx.parcelize.Parcelize

@Parcelize
data class KhataAccount(

    @SerializedName("doc_id")
    var docId: String? = null,

    @SerializedName("shop_id")
    @get:PropertyName("shop_id") @set:PropertyName("shop_id")
    var shopId: String? = null,

    @SerializedName("customer_id")
    @get:PropertyName("customer_id") @set:PropertyName("customer_id")
    var customerId: String? = null,

    @SerializedName("customer_name")
    @get:PropertyName("customer_name") @set:PropertyName("customer_name")
    var customerName: String? = null,

    @SerializedName("phone")
    var phone: String? = null,

    @SerializedName("balance")
    var balance: Double? = 0.0,

    @SerializedName("updated_at")
    var updatedAt: String? = null,

    @SerializedName("shop_name")
    @get:PropertyName("shop_name") @set:PropertyName("shop_name")
    var shopName: String? = "",

    @SerializedName("pending_cash")
    @get:PropertyName("pending_cash") @set:PropertyName("pending_cash")
    var pendingCash: Double? = 0.0,

    @SerializedName("pending_status")
    @get:PropertyName("pending_status") @set:PropertyName("pending_status")
    var pendingStatus: String? = null,

    @SerializedName("pending_request_id")
    @get:PropertyName("pending_request_id") @set:PropertyName("pending_request_id")
    var pendingRequestId: String? = null,

    ) : Parcelable


data class KhataAccountsResponse(
    val success: Boolean,
    val accounts: List<KhataAccount>?
)
